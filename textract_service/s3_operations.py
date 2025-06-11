# textract_service/s3_operations.py

import os
from botocore.exceptions import ClientError
from .aws_clients import s3_client, S3_BUCKET_NAME # Importa o s3_client e S3_BUCKET_NAME

async def upload_file_to_s3(file_path: str, s3_object_key: str) -> str: # Removi 'destination_folder'
    """
    Carrega um arquivo para o S3 e retorna a chave do objeto.
    A s3_object_key deve ser o caminho completo do objeto no S3 (ex: 'pasta/nome_arquivo.pdf').
    """
    # --- INÍCIO DO CÓDIGO DE DEBUG ---
    print(f"\n[DEBUG S3] Tentando fazer upload do arquivo local: {file_path}")
    print(f"[DEBUG S3] Para o bucket: {S3_BUCKET_NAME}")
    print(f"[DEBUG S3] Com a chave FINAL do objeto S3: {s3_object_key}")
    # --- FIM DO CÓDIGO DE DEBUG ---

    try:
        # Nota: O método upload_file do boto3 é síncrono.
        # Para um ambiente assíncrono (FastAPI), pode ser melhor usar run_in_threadpool
        # ou aiobotocore para operações S3 maiores em produção.
        # Para este exemplo, manteremos a simplicidade.
        s3_client.upload_file(file_path, S3_BUCKET_NAME, s3_object_key)

        # --- INÍCIO DO CÓDIGO DE DEBUG ---
        print(f"[DEBUG S3] Upload de '{file_path}' para s3://{S3_BUCKET_NAME}/{s3_object_key} concluído com sucesso.")
        # --- FIM DO CÓDIGO DE DEBUG ---
        return s3_object_key
    except ClientError as e:
        # --- INÍCIO DO CÓDIGO DE DEBUG ---
        print(f"[DEBUG S3] Erro durante o upload para S3: {e}")
        # --- FIM DO CÓDIGO DE DEBUG ---
        raise Exception(f"Erro ao carregar arquivo para S3: {e}")

async def delete_s3_object(s3_object_key: str): # Renomeado de delete_file_from_s3 para delete_s3_object
    """
    Exclui um objeto do S3.
    """
    # --- INÍCIO DO CÓDIGO DE DEBUG ---
    print(f"\n[DEBUG S3] Tentando excluir o objeto S3: {s3_object_key} do bucket: {S3_BUCKET_NAME}")
    # --- FIM DO CÓDIGO DE DEBUG ---
    try:
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_object_key)
        # --- INÍCIO DO CÓDIGO DE DEBUG ---
        print(f"[DEBUG S3] Objeto S3 '{s3_object_key}' excluído com sucesso.")
        # --- FIM DO CÓDIGO DE DEBUG ---
    except ClientError as e:
        # --- INÍCIO DO CÓDIGO DE DEBUG ---
        print(f"[DEBUG S3] Erro ao excluir objeto S3: {e}")
        # --- FIM DO CÓDIGO DE DEBUG ---
        # Não levante exceção aqui para não impedir a limpeza de arquivos residuais
        pass

def get_file_size_mb(document_key: str) -> float:
    """Obtém o tamanho do arquivo em MB do S3.
    
    Args:
        document_key (str): A chave (nome) do documento no S3.

    Returns:
        float: O tamanho do arquivo em MB, ou 0.0 se não encontrado, -1.0 em caso de erro.
    """
    try:
        response = s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=document_key)
        size_bytes = response['ContentLength']
        size_mb = round(size_bytes / (1024 * 1024), 2)
        return size_mb
    except s3_client.exceptions.NoSuchKey:
        return 0.0 # Retorna 0 se o arquivo não for encontrado (pode ter sido deletado)
    except Exception as e:
        print(f"Erro ao obter tamanho do arquivo {document_key} do S3: {e}")
        return -1.0 # Indica erro
