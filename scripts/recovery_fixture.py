"""Exercise the real dump/encrypt/decrypt/restore path on two disposable databases."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from cryptography.fernet import Fernet
import sqlalchemy as sa
from recovery_drill import database


def main():
    # CI supplies an isolated Postgres service. Never falls back to backend/.env.
    admin_url = os.environ["RECOVERY_FIXTURE_DATABASE_URL"]
    admin = database(admin_url).execution_options(isolation_level="AUTOCOMMIT")
    names = ["recovery_"+uuid.uuid4().hex for _ in range(2)]
    created = []
    try:
        with admin.connect() as c:
            for name in names:
                c.exec_driver_sql(f'CREATE DATABASE "{name}"'); created.append(name)
        urls = [sa.engine.make_url(admin_url).set(database=n).render_as_string(hide_password=False) for n in names]
        for url in urls:
            engine = database(url)
            with engine.begin() as c:
                c.exec_driver_sql("CREATE EXTENSION vector")
                c.exec_driver_sql("CREATE SCHEMA auth")
                c.exec_driver_sql("CREATE TABLE auth.users (id uuid PRIMARY KEY)")
                c.exec_driver_sql("CREATE TABLE public.projects (id uuid PRIMARY KEY, owner_id uuid REFERENCES auth.users(id), name text)")
                c.exec_driver_sql("CREATE TABLE public.files (id uuid PRIMARY KEY,project_id uuid REFERENCES public.projects(id),storage_path text,content_sha256 text,markdown_storage_path text,markdown_sha256 text)")
                c.exec_driver_sql("CREATE TABLE public.chunks (id bigserial PRIMARY KEY,project_id uuid REFERENCES public.projects(id),file_id uuid REFERENCES public.files(id),content text,embedding vector(3))")
            engine.dispose()
        data = "Synthetic recovery policy: return within 30 days. தமிழ்".encode()
        owner,project,file = uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
        engine = database(urls[0])
        with engine.begin() as c:
            c.execute(sa.text("INSERT INTO auth.users VALUES (:id)"),{"id":owner})
            c.execute(sa.text("INSERT INTO public.projects VALUES (:id,:owner,'Synthetic restore fixture')"),{"id":project,"owner":owner})
            c.execute(sa.text("INSERT INTO public.files VALUES (:id,:project,'fixture.txt',:hash,'fixture.md',:hash)"),{"id":file,"project":project,"hash":hashlib.sha256(data).hexdigest()})
            c.execute(sa.text("INSERT INTO public.chunks(project_id,file_id,content,embedding) VALUES (:project,:file,:content,'[1,0,0]')"),{"project":project,"file":file,"content":data.decode()})
        engine.dispose()
        with tempfile.TemporaryDirectory(prefix="oreag-fixture-") as tmp:
            folder = Path(tmp)
            (folder/"fixture.txt").write_bytes(data);(folder/"fixture.md").write_bytes(data)
            env = {**os.environ,"SOURCE_DATABASE_URL":urls[0],"RECOVERY_TARGET_DATABASE_URL":urls[1],"RECOVERY_TARGET_ACK":"EMPTY_ISOLATED_TARGET","RECOVERY_BACKUP_KEY":Fernet.generate_key().decode()}
            subprocess.run([sys.executable,str(Path(__file__).with_name("recovery_drill.py")),"--backup",str(folder/"fixture.oreag-backup"),"--source-files",str(folder),"--report","recovery-fixture-report.json"],env=env,check=True)
            # A second restore must refuse to touch the now populated target.
            repeated = subprocess.run([sys.executable,str(Path(__file__).with_name("recovery_drill.py")),"--backup",str(folder/"fixture.oreag-backup"),"--restore-existing","--report",str(folder/"should-not-exist.json")],env=env)
            if repeated.returncode == 0: raise AssertionError("Populated-target protection failed")
        print("Synthetic database, file checksums and vector retrieval verified; populated target was rejected.")
    finally:
        with admin.connect() as c:
            for name in created:
                # Generated disposable databases only; never the caller's database.
                c.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


if __name__ == "__main__": main()
