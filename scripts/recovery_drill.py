"""Encrypted application-data backup and restore verification against an EMPTY, migrated target.

Requires pg_dump/pg_restore, psycopg, SQLAlchemy, cryptography and (for cloud files) httpx.
Source is read-only. The target must be a separate database with matching auth/public schemas.
No schema, table or existing record is deleted by this program.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile
import uuid
from contextlib import contextmanager

from cryptography.fernet import Fernet
import sqlalchemy as sa

MAGIC = b"OREAG-BACKUP-1\n"
CHUNK = 8 * 1024 * 1024


def crypt_file(source, target, key, decrypt=False):
    cipher = Fernet(key)
    with open(source, "rb") as src, open(target, "xb") as dst:
        if decrypt:
            if src.read(len(MAGIC)) != MAGIC: raise ValueError("Invalid backup format")
            index = 0
            while True:
                length = src.read(4)
                if len(length) != 4: raise ValueError("Truncated backup")
                size = struct.unpack(">I", length)[0]
                if size > 2 * CHUNK: raise ValueError("Invalid backup frame")
                payload = cipher.decrypt(src.read(size))
                if payload[:8] != struct.pack(">Q", index): raise ValueError("Reordered backup frame")
                index += 1
                if len(payload) == 8:
                    if src.read(1): raise ValueError("Trailing backup bytes")
                    break
                dst.write(payload[8:])
        else:
            dst.write(MAGIC)
            index = 0
            while True:
                data = src.read(CHUNK)
                token = cipher.encrypt(struct.pack(">Q", index)+data)
                dst.write(struct.pack(">I",len(token))); dst.write(token)
                index += 1
                if not data: break


def database(url):
    return sa.create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1), connect_args={"prepare_threshold":None})


def pg(command, url, *args):
    parsed = sa.engine.make_url(url)
    env = os.environ.copy()
    env.update(PGHOST=parsed.host or "localhost", PGPORT=str(parsed.port or 5432), PGDATABASE=parsed.database or "postgres", PGUSER=parsed.username or "postgres", PGPASSWORD=parsed.password or "")
    if "sslmode" in parsed.query: env["PGSSLMODE"] = parsed.query["sslmode"]
    # Credentials are passed through the environment, never CLI arguments or logs.
    result = subprocess.run([command,*map(str,args)],env=env,capture_output=True)
    if result.returncode: raise RuntimeError(f"{command} failed; check client/server compatibility and target privileges. Details withheld to avoid exposing private data.")


def table_names(connection):
    return connection.execute(sa.text("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('public','auth') ORDER BY 1,2")).all()


def quoted(connection, schema, table):
    q = connection.dialect.identifier_preparer.quote
    return q(schema)+"."+q(table)


def fingerprints(connection):
    result = {}
    for schema, table in table_names(connection):
        name = quoted(connection,schema,table)
        digest, count = hashlib.sha256(), 0
        # Sorted canonical rows verify every value, including vectors and ownership.
        rows = connection.execution_options(stream_results=True).exec_driver_sql(f'SELECT to_jsonb(t)::text FROM {name} t ORDER BY to_jsonb(t)::text COLLATE "C"')
        for (value,) in rows:
            digest.update(value.encode()+b"\n"); count += 1
        result[f"{schema}.{table}"] = {"rows":count,"sha256":digest.hexdigest()}
    return result


def schema_signature(connection):
    return [list(row) for row in connection.execute(sa.text("SELECT table_schema,table_name,column_name,udt_name,is_nullable,is_generated FROM information_schema.columns WHERE table_schema IN ('public','auth') ORDER BY 1,2,ordinal_position"))]


def snapshot(source_url, directory, source_files=None):
    engine = database(source_url)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            snapshot_id = connection.scalar(sa.text("SELECT pg_export_snapshot()"))
            manifest = {"format":1,"schema":schema_signature(connection),"tables":fingerprints(connection),"files":[]}
            pg("pg_dump",source_url,"--format=custom","--data-only","--no-owner","--no-acl","--schema=public","--schema=auth",f"--snapshot={snapshot_id}","--file",directory/"database.dump")
            objects = connection.execute(sa.text("SELECT storage_path,content_sha256,markdown_storage_path,markdown_sha256 FROM public.files")).all()
            seen = set()
            for original, original_hash, markdown, markdown_hash in objects:
                for path, expected in ((original,original_hash),(markdown,markdown_hash)):
                    if not path or path in seen: continue
                    seen.add(path)
                    if source_files:
                        root = source_files.resolve()
                        candidate = (root/path).resolve()
                        if not candidate.is_relative_to(root): raise ValueError("Unsafe storage object path")
                        data = candidate.read_bytes()
                    else:
                        import httpx
                        from urllib.parse import quote
                        host = os.environ["SUPABASE_URL"].rstrip("/")
                        if not host.startswith("https://"): raise ValueError("Cloud storage requires HTTPS")
                        bucket = os.environ.get("STORAGE_BUCKET","project-files")
                        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
                        with httpx.Client(timeout=120,follow_redirects=False) as client:
                            response = client.get(f"{host}/storage/v1/object/{quote(bucket,safe='')}/{quote(path,safe='/')}",headers={"Authorization":"Bearer "+key,"apikey":key})
                            response.raise_for_status(); data = response.content
                    digest = hashlib.sha256(data).hexdigest()
                    if expected and digest != expected: raise ValueError("Storage content does not match the database snapshot")
                    local = f"objects/{len(manifest['files'])}"
                    (directory/"objects").mkdir(exist_ok=True)
                    (directory/local).write_bytes(data)
                    manifest["files"].append({"path":path,"entry":local,"sha256":digest,"bytes":len(data)})
            manifest["retrieval"] = [dict(row._mapping) for row in connection.execute(sa.text("SELECT id,project_id::text AS project_id,embedding::text AS embedding,vector_dims(embedding) AS dimensions FROM public.chunks WHERE embedding IS NOT NULL AND vector_norm(embedding)>0 ORDER BY id LIMIT 5"))]
            (directory/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            return manifest
    finally: engine.dispose()


def restore(target_url, directory):
    manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    engine = database(target_url)
    try:
        with engine.connect() as connection:
            if schema_signature(connection) != manifest["schema"]: raise ValueError("Target schema differs; apply matching migrations first")
            for schema, table in table_names(connection):
                if connection.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {quoted(connection,schema,table)} LIMIT 1)")):
                    raise ValueError("Target contains data; refusing to restore")
        # Single transaction + trigger suppression avoid outbox activity and FK load ordering.
        # Requires the dedicated target's restore administrator; never disables source triggers.
        pg("pg_restore",target_url,"--data-only","--no-owner","--no-acl","--exit-on-error","--single-transaction","--disable-triggers", "--dbname",sa.engine.make_url(target_url).database,directory/"database.dump")
        with engine.connect() as connection:
            if fingerprints(connection) != manifest["tables"]: raise ValueError("Restored row fingerprints differ")
            for probe in manifest["retrieval"]:
                distance = connection.scalar(sa.text("SELECT embedding <=> CAST(:vector AS vector) FROM public.chunks WHERE id=:id AND project_id=CAST(:project AS uuid)"),{"vector":probe["embedding"],"id":probe["id"],"project":probe["project_id"]})
                if distance is None or abs(distance)>1e-5: raise ValueError("Restored vector differs")
                hits = connection.execute(sa.text("SELECT id FROM public.chunks WHERE project_id=CAST(:project AS uuid) AND vector_dims(embedding)=:dims ORDER BY embedding <=> CAST(:vector AS vector) LIMIT 5"),{"project":probe["project_id"],"dims":probe["dimensions"],"vector":probe["embedding"]}).all()
                if not hits: raise ValueError("Restored retrieval returned no rows")
        for item in manifest["files"]:
            data = (directory/item["entry"]).read_bytes()
            if len(data)!=item["bytes"] or hashlib.sha256(data).hexdigest()!=item["sha256"]: raise ValueError("Restored file checksum differs")
        return {"verified":True,"tables":len(manifest["tables"]),"rows":sum(t["rows"] for t in manifest["tables"].values()),"files":len(manifest["files"]),"retrieval_probes":len(manifest["retrieval"]),"scope":"auth/public data and stored original/markdown bytes; excludes platform configuration and remote bucket writes"}
    finally: engine.dispose()


@contextmanager
def disposable_target(template_url, enabled):
    if not enabled:
        yield template_url
        return
    parsed = sa.engine.make_url(template_url)
    template = database(template_url)
    admin = database(parsed.set(database="postgres").render_as_string(hide_password=False)).execution_options(isolation_level="AUTOCOMMIT")
    name = "oreag_restore_"+uuid.uuid4().hex
    created = False
    try:
        with template.connect() as connection:
            for schema, table in table_names(connection):
                if connection.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {quoted(connection,schema,table)} LIMIT 1)")):
                    raise ValueError("Recovery template contains data")
        template.dispose()
        with admin.connect() as connection:
            q = connection.dialect.identifier_preparer.quote
            connection.exec_driver_sql(f"CREATE DATABASE {q(name)} TEMPLATE {q(parsed.database)}")
            created = True
        yield parsed.set(database=name).render_as_string(hide_password=False)
    finally:
        if created:
            with admin.connect() as connection:
                # Only the randomly named database created by this invocation.
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        template.dispose()
        admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup",type=Path,required=True,help="New encrypted backup path; never overwritten")
    parser.add_argument("--source-files",type=Path,help="Local object fixture directory; omit for Supabase Storage")
    parser.add_argument("--report",type=Path,default=Path("recovery-report.json"))
    parser.add_argument("--restore-existing",action="store_true",help="Verify an existing encrypted backup instead of taking a new one")
    parser.add_argument("--disposable-target",action="store_true",help="Clone the empty target template into a fresh database, verify, then remove the clone; requires CREATEDB")
    args = parser.parse_args()
    source_url, target_url = os.getenv("SOURCE_DATABASE_URL"), os.environ["RECOVERY_TARGET_DATABASE_URL"]
    if os.getenv("RECOVERY_TARGET_ACK") != "EMPTY_ISOLATED_TARGET": parser.error("Set RECOVERY_TARGET_ACK=EMPTY_ISOLATED_TARGET for a dedicated empty target with all workers disabled")
    if not args.restore_existing:
        if not source_url: parser.error("Set SOURCE_DATABASE_URL")
        a,b = sa.engine.make_url(source_url),sa.engine.make_url(target_url)
        if (a.host,a.port or 5432,a.database)==(b.host,b.port or 5432,b.database): parser.error("Source and target cannot be the same database")
    key = os.environ["RECOVERY_BACKUP_KEY"].encode()
    # Validate encryption before reading any source data.
    Fernet(key)
    with tempfile.TemporaryDirectory(prefix="oreag-recovery-") as temp:
        root = Path(temp); root.chmod(0o700)
        if not args.restore_existing:
            content = root/"snapshot";content.mkdir()
            snapshot(source_url,content,args.source_files)
            archive = root/"snapshot.zip"
            with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED) as z:
                for path in content.rglob("*"):
                    if path.is_file(): z.write(path,path.relative_to(content).as_posix())
            crypt_file(archive,args.backup,key)
        decoded = root/"decoded.zip"
        crypt_file(args.backup,decoded,key,decrypt=True)
        restored = root/"restored";restored.mkdir()
        with zipfile.ZipFile(decoded) as z:
            for item in z.infolist():
                if not (restored/item.filename).resolve().is_relative_to(restored.resolve()): raise ValueError("Unsafe archive entry")
            z.extractall(restored)
        with disposable_target(target_url,args.disposable_target) as isolated_url:
            report = restore(isolated_url,restored)
        args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        # DB/storage exceptions can contain private content or connection strings.
        print(f"Recovery verification failed ({type(exc).__name__}); no successful report was written.")
        raise SystemExit(1) from None
