# textract_service/textract_logic.py

import time
from typing import Dict, List, Any
from fastapi import HTTPException
from textract_service.aws_clients import textract_client, S3_BUCKET_NAME # Importa S3_BUCKET_NAME aqui

def start_textract_job(document_key: str) -> str:
    """Inicia o trabalho de análise de documento no Textract.
    
    Args:
        document_key (str): A chave (nome) do documento no S3.

    Returns:
        str: O JobId retornado pelo Textract.
    
    Raises:
        HTTPException: Se houver um erro ao iniciar o job.
    """
    try:
        response = textract_client.start_document_analysis(
            DocumentLocation={'S3Object': {'Bucket': S3_BUCKET_NAME, 'Name': document_key}}, # CORRIGIDO: Usando S3_BUCKET_NAME
            FeatureTypes=["TABLES", "FORMS", "SIGNATURES"]
        )
        return response['JobId']
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao iniciar job do Textract: {e}")

def is_job_complete(job_id: str) -> (str, Dict[str, Any]):
    """Verifica o status do trabalho do Textract.
    
    Args:
        job_id (str): O JobId do trabalho do Textract.

    Returns:
        tuple: (status: str, response: dict) - O status do job e a resposta completa.
    
    Raises:
        HTTPException: Se o JobId for inválido ou ocorrer outro erro.
    """
    try:
        response = textract_client.get_document_analysis(JobId=job_id)
        status = response['JobStatus']
        return status, response
    except textract_client.exceptions.InvalidJobIdException:
        raise HTTPException(status_code=404, detail="Job ID inválido ou não encontrado.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao verificar status do job: {e}")

def get_job_results(job_id: str) -> List[Dict[str, Any]]:
    """Obtém todos os resultados de um trabalho do Textract, lidando com paginação.
    
    Args:
        job_id (str): O JobId do trabalho do Textract.

    Returns:
        List[Dict[str, Any]]: Uma lista de respostas do Textract, cada uma representando uma "página" de dados.
    
    Raises:
        HTTPException: Se o JobId for inválido ou ocorrer outro erro.
    """
    pages_data = []
    next_token = None
    
    while True:
        try:
            if next_token:
                response = textract_client.get_document_analysis(JobId=job_id, NextToken=next_token)
            else:
                response = textract_client.get_document_analysis(JobId=job_id)

            pages_data.append(response)
            next_token = response.get('NextToken', None)
            
            if not next_token:
                break
            time.sleep(0.5) # Pequena pausa para evitar throttling
        except textract_client.exceptions.InvalidJobIdException:
            raise HTTPException(status_code=404, detail="Job ID inválido ou não encontrado.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao recuperar resultados do job: {e}")

    return pages_data

def extract_lines_from_textract_response(textract_pages_data: List[Dict[str, Any]]) -> List[str]:
    """
    Extrai todas as linhas de texto dos dados brutos de resposta do Textract,
    garantindo que as linhas sejam associadas corretamente às suas páginas físicas.
    
    Args:
        textract_pages_data (List[Dict[str, Any]]): Lista de respostas paginadas do Textract.

    Returns:
        List[str]: Uma lista concatenada de todas as linhas de texto extraídas.
    """
    all_lines = []
    
    # Mapeamento de block_id para o bloco correspondente para acesso rápido
    blocks_map = {}
    for page_response in textract_pages_data:
        for block in page_response.get('Blocks', []):
            blocks_map[block['Id']] = block

    # Itera sobre os blocos para encontrar os blocos de tipo 'PAGE'
    for page_response in textract_pages_data:
        for block in page_response.get('Blocks', []):
            if block['BlockType'] == 'PAGE':
                # Encontra os blocos 'LINE' que são filhos da 'PAGE' atual
                if 'Relationships' in block:
                    for relationship in block['Relationships']:
                        if relationship['Type'] == 'CHILD':
                            for child_id in relationship['Ids']:
                                child_block = blocks_map.get(child_id)
                                if child_block and child_block['BlockType'] == 'LINE' and 'Text' in child_block:
                                    all_lines.append(child_block['Text'])

    return all_lines