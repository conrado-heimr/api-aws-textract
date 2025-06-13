import os
from botocore.exceptions import ClientError
from starlette.concurrency import run_in_threadpool # Importação necessária para assincronicidade
import logging # Importa o logger para mensagens de log

# Importa o s3_client e S3_BUCKET_NAME do módulo aws_clients
from .aws_clients import s3_client, S3_BUCKET_NAME 

# Configuração do logger (garantir que ele use o logger principal da aplicação)
logger = logging.getLogger("BrokerAPI")

# --- Funções AUXILIARES SÍNCRONAS (a serem chamadas por run_in_threadpool) ---
# Estas funções fazem o trabalho real com boto3 e são síncronas.

def _upload_file_to_s3_sync(file_path: str, s3_object_key: str) -> str:
    """
    Carrega um arquivo para o S3 de forma síncrona.
    """
    s3_client.upload_file(file_path, S3_BUCKET_NAME, s3_object_key)
    return s3_object_key

def _delete_s3_object_sync(s3_object_key: str):
    """
    Exclui um objeto do S3 de forma síncrona.
    """
    s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_object_key)

def _get_file_size_mb_sync(document_key: str) -> float:
    """
    Obtém o tamanho do arquivo em MB do S3 de forma síncrona.
    """
    response = s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=document_key)
    size_bytes = response['ContentLength']
    size_mb = round(size_bytes / (1024 * 1024), 2)
    return size_mb

# --- Funções ASSÍNCRONAS (que o main.py vai chamar) ---
# Estas funções usarão run_in_threadpool para executar as funções síncronas acima.

async def upload_file_to_s3(file_path: str, s3_object_key: str) -> str:
    """
    Carrega um arquivo para o S3 de forma assíncrona e retorna a chave do objeto.
    A s3_object_key deve ser o caminho completo do objeto no S3 (ex: 'pasta/nome_arquivo.pdf').
    """
    logger.info(f"Tentando fazer upload do arquivo local: {file_path} para o bucket: {S3_BUCKET_NAME} com a chave: {s3_object_key}")
    try:
        key = await run_in_threadpool(_upload_file_to_s3_sync, file_path, s3_object_key)
        logger.info(f"Upload de '{file_path}' para s3://{S3_BUCKET_NAME}/{s3_object_key} concluído com sucesso.")
        return key
    except ClientError as e:
        logger.error(f"Erro ClientError durante o upload para S3: {e}", exc_info=True)
        raise Exception(f"Erro ao carregar arquivo para S3: {e}")
    except Exception as e:
        logger.error(f"Exceção inesperada durante o upload para S3: {e}", exc_info=True)
        raise Exception(f"Erro interno ao carregar arquivo para S3: {e}")

async def delete_s3_object(s3_object_key: str):
    """
    Exclui um objeto do S3 de forma assíncrona.
    """
    logger.info(f"Tentando excluir o objeto S3: {s3_object_key} do bucket: {S3_BUCKET_NAME}")
    try:
        await run_in_threadpool(_delete_s3_object_sync, s3_object_key)
        logger.info(f"Objeto S3 '{s3_object_key}' excluído com sucesso.")
    except ClientError as e:
        # ClientError: Por exemplo, NoSuchKey (se o objeto já foi excluído por outro processo)
        # Registramos, mas não levantamos exceção para não impedir a limpeza.
        logger.warning(f"ClientError ao excluir objeto S3 '{s3_object_key}': {e}. Pode ser que já não exista.", exc_info=True)
    except Exception as e:
        logger.error(f"Exceção inesperada ao excluir objeto S3 '{s3_object_key}': {e}", exc_info=True)
        # Decisão: Levantar ou não. Para limpeza, geralmente não levantamos
        # para que o processo principal não falhe se a limpeza falhar.
        pass 

async def get_file_size_mb(document_key: str) -> float:
    """Obtém o tamanho do arquivo em MB do S3 de forma assíncrona.
    
    Args:
        document_key (str): A chave (nome) do documento no S3.

    Returns:
        float: O tamanho do arquivo em MB, ou 0.0 se não encontrado, -1.0 em caso de erro.
    """
    logger.info(f"Tentando obter o tamanho do arquivo S3: {document_key} do bucket: {S3_BUCKET_NAME}")
    try:
        size_mb = await run_in_threadpool(_get_file_size_mb_sync, document_key)
        logger.info(f"Tamanho do arquivo '{document_key}': {size_mb} MB.")
        return size_mb
    except s3_client.exceptions.NoSuchKey:
        logger.warning(f"Arquivo S3 '{document_key}' não encontrado. Retornando tamanho 0.0.")
        return 0.0 # Retorna 0 se o arquivo não for encontrado (pode ter sido deletado)
    except ClientError as e:
        logger.error(f"ClientError ao obter tamanho do arquivo {document_key} do S3: {e}", exc_info=True)
        return -1.0 # Indica erro específico do S3
    except Exception as e:
        logger.error(f"Exceção inesperada ao obter tamanho do arquivo {document_key} do S3: {e}", exc_info=True)
        return -1.0 # Indica erro geral