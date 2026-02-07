from pathlib import Path
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_core.vectorstores import Chroma

# Define the directory containing the documents
DOC_DIR = Path("docs")


# Function for Load documents from the specified directory
def load_docs():
    docs = []
    for fp in DOC_DIR.glob("*"):
        if fp.is_file():
            docs.extend(TextLoader(str(fp),encoding="utf-8").load())
    return docs


# Define the text splitter with specified chunk size and overlap
splitters = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200
    )

# Chunking
chunks = splitters.create_documents(load_docs())

embeddings = OpenAIEmbeddings()
Chroma.from_documents(
    documents=chunks, 
    embedding=embeddings, 
    collection_name="my_collection"
    )

print("Indexing completed successfully.")