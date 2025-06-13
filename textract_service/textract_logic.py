# textract_service/textract_logic.py

import time
from typing import Dict, List, Any, Tuple
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool # Importação necessária para assincronicidade

# Importa S3_BUCKET_NAME e textract_client do módulo aws_clients
from .aws_clients import textract_client, S3_BUCKET_NAME 

# --- Funções AUXILIARES SÍNCRONAS (a serem chamadas por run_in_threadpool) ---
# Estas funções fazem o trabalho real com boto3 e são síncronas.

def _start_textract_job_sync(document_key: str) -> str:
    """Inicia o trabalho de detecção de texto no Textract (síncrono)."""
    response = textract_client.start_document_text_detection(
        DocumentLocation={'S3Object': {'Bucket': S3_BUCKET_NAME, 'Name': document_key}}
    )
    return response['JobId']

def _is_job_complete_sync(job_id: str) -> Tuple[str, Dict[str, Any]]:
    """Verifica o status do trabalho de detecção de texto do Textract (síncrono)."""
    response = textract_client.get_document_text_detection(JobId=job_id)
    status = response['JobStatus']
    # A resposta de get_document_text_detection não tem 'Warnings' por padrão como a de analysis
    # Mas a estrutura do retorno da função is_job_complete espera dois valores.
    return status, response # Retorna a resposta completa para consistência, mesmo que não usada sempre

def _get_job_results_sync(job_id: str) -> List[Dict[str, Any]]:
    """Obtém todos os resultados paginados de um trabalho de detecção de texto do Textract (síncrono)."""
    full_results_list = []
    next_token = None
    
    while True:
        if next_token:
            response = textract_client.get_document_text_detection(JobId=job_id, NextToken=next_token)
        else:
            response = textract_client.get_document_text_detection(JobId=job_id)
        
        full_results_list.append(response)
        next_token = response.get('NextToken') # .get() para lidar com a ausência de 'NextToken'
        
        if not next_token:
            break
        time.sleep(0.5) # Pequena pausa para evitar throttling

    return full_results_list

# --- Funções ASSÍNCRONAS (que o main.py vai chamar) ---
# Estas funções usarão run_in_threadpool para executar as funções síncronas acima,
# permitindo que a FastAPI continue respondendo a outras requisições.

async def start_textract_job(document_key: str) -> str:
    """Inicia o trabalho de detecção de texto no Textract de forma assíncrona.
    
    Args:
        document_key (str): A chave (nome) do documento no S3.

    Returns:
        str: O JobId retornado pelo Textract.
    
    Raises:
        HTTPException: Se houver um erro ao iniciar o job.
    """
    try:
        return await run_in_threadpool(_start_textract_job_sync, document_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao iniciar job do Textract: {e}")

async def is_job_complete(job_id: str) -> Tuple[str, Dict[str, Any]]:
    """Verifica o status do trabalho de detecção de texto do Textract de forma assíncrona.
    
    Args:
        job_id (str): O JobId do trabalho do Textract.

    Returns:
        tuple: (status: str, response: dict) - O status do job e a resposta completa.
    
    Raises:
        HTTPException: Se o JobId for inválido ou ocorrer outro erro.
    """
    try:
        return await run_in_threadpool(_is_job_complete_sync, job_id)
    except textract_client.exceptions.InvalidJobIdException:
        raise HTTPException(status_code=404, detail="Job ID inválido ou não encontrado.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao verificar status do job: {e}")

async def get_job_results(job_id: str) -> List[Dict[str, Any]]:
    """Obtém todos os resultados de um trabalho de detecção de texto do Textract de forma assíncrona, lidando com paginação.
    
    Args:
        job_id (str): O JobId do trabalho do Textract.

    Returns:
        List[Dict[str, Any]]: Uma lista de respostas do Textract, cada uma representando uma "página" de dados.
    
    Raises:
        HTTPException: Se o JobId for inválido ou ocorrer outro erro.
    """
    try:
        return await run_in_threadpool(_get_job_results_sync, job_id)
    except textract_client.exceptions.InvalidJobIdException:
        raise HTTPException(status_code=404, detail="Job ID inválido ou não encontrado.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao recuperar resultados do job: {e}")

# Esta função é puramente computacional e não precisa ser assíncrona com run_in_threadpool
def extract_lines_from_textract_response(textract_pages_data: List[Dict[str, Any]]) -> List[str]:
    """
    Extrai todas as linhas de texto dos dados brutos de resposta do Textract.
    Esta versão é otimizada para a saída de 'get_document_text_detection'.
    
    Args:
        textract_pages_data (List[Dict[str, Any]]): Lista de respostas paginadas do Textract.

    Returns:
        List[str]: Uma lista concatenada de todas as linhas de texto extraídas.
    """
    all_lines = []
    for page_data in textract_pages_data:
        for block in page_data['Blocks']:
            if block['BlockType'] == 'LINE' and 'Text' in block:
                all_lines.append(block['Text'])
    return all_lines