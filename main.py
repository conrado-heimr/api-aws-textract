# Importações necessárias (manter as atuais)
import time
import os
import uuid
import aiofiles
import httpx
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

# --- ADIÇÃO PARA LOGGING PERSONALIZADO ---
import logging
from logging.handlers import RotatingFileHandler
from utils.custom_log_filter import request_context_filter # IMPORTA SEU FILTRO PERSONALIZADO

# Importa as funções e clientes dos novos módulos
from textract_service.aws_clients import S3_BUCKET_NAME 
from textract_service.textract_logic import start_textract_job, is_job_complete, get_job_results, extract_lines_from_textract_response
from textract_service.s3_operations import upload_file_to_s3, delete_s3_object, get_file_size_mb
from utils.text_sanitizer import sanitize_text_for_sql

# --- CONFIGURAÇÃO DO LOGGER ---
LOG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")
LOG_MAX_BYTES = 5 * 1024 * 1024 # 5 MB
LOG_BACKUP_COUNT = 10 # Manter 10 arquivos de backup

os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)

logger = logging.getLogger("BrokerAPI")
logger.setLevel(logging.INFO)

log_format = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s [method=%(method)s, endpoint=%(endpoint)s, status_code=%(status_code)s]'
)

file_handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
logger.addHandler(console_handler)

logger.addFilter(request_context_filter)

app = FastAPI(
    title="AWS Textract Document Analysis API",
    description="API para analisar documentos PDF/Imagens usando AWS Textract, com upload direto e retorno de resultados.",
    version="1.0.0",
    root_path="/textract"
)

@app.middleware("http")
async def add_request_context_to_logs(request: Request, call_next):
    request_context_filter.method = request.method
    request_context_filter.endpoint = request.url.path
    request_context_filter.status_code = None

    response = Response("Internal server error", status_code=500)
    try:
        response = await call_next(request)
    except HTTPException as http_exc:
        request_context_filter.status_code = http_exc.status_code
        logger.error(f"HTTPException durante a requisição: {http_exc.detail}", exc_info=True)
        raise http_exc
    except Exception as e:
        request_context_filter.status_code = 500
        logger.critical(f"Exceção CRÍTICA não tratada durante a requisição: {str(e)}", exc_info=True)
        raise e
    finally:
        if request_context_filter.status_code is None:
            request_context_filter.status_code = response.status_code
        request_context_filter.method = None
        request_context_filter.endpoint = None
        request_context_filter.status_code = None
        return response

TEMP_FILES_DIR = os.getenv("TEMP_FILES_DIR", "/tmp")

def format_duration(seconds: float) -> str:
    """Formata a duração em HH:MM:SS.millis."""
    millis = int((seconds - int(seconds)) * 1000)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}.{millis:03}"

@app.get("/", response_class=HTMLResponse, summary="Página inicial")
async def read_root():
    logger.info("Acessando página inicial.")
    return """
    <html>
        <head>
            <title>AWS Textract API</title>
        </head>
        <body>
            <h1>Bem-vindo à API de Análise de Documentos com AWS Textract</h1>
            <p>Use o endpoint <code>/analyze_document/</code> para enviar um documento ou fornecer uma URL e obter o <b>ID do Job</b>.</p>
            <p>Em seguida, use <code>/get_analysis_status/{job_id}</code> para verificar o status e <code>/get_analysis_results/{job_id}</code> para obter os resultados quando o job estiver concluído.</p>
            <p>Você pode testar a API através da interface Swagger UI em <a href="/docs">/docs</a> ou ReDoc em <a href="/redoc">/redoc</a>.</p>
        </body>
    </html>
    """


### **Endpoint Modificado: `/analyze_document/`**
@app.post("/analyze_document/", summary="Inicia a análise de um documento PDF/Imagem e retorna o Job ID para consulta posterior.")
async def analyze_document(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None, description="O documento (PDF, JPEG, PNG) a ser analisado (upload)."),
    document_url: Optional[str] = Form(None, description="URL de onde o documento (PDF, JPEG, PNG) será baixado.")
):
    """
    Recebe um arquivo de documento via upload ou uma URL, faz o download/upload para S3,
    e **IMEDIATAMENTE** inicia um trabalho de análise com AWS Textract, retornando o Job ID.
    A responsabilidade de verificar o status e obter os resultados é do cliente, usando
    os endpoints `/get_analysis_status/{job_id}` e `/get_analysis_results/{job_id}`.
    Um dos dois parâmetros (file ou document_url) deve ser fornecido.
    """
    logger.info("--- INÍCIO DA EXECUÇÃO DO /analyze_document/ ---")
    if not file and not document_url:
        logger.error("Nenhum arquivo ou URL fornecido.")
        raise HTTPException(status_code=400, detail="Por favor, forneça um arquivo ou uma URL de documento.")
    if file and document_url:
        logger.error("Ambos arquivo e URL fornecidos.")
        raise HTTPException(status_code=400, detail="Forneça apenas um: arquivo ou URL de documento, não ambos.")

    file_extension: str
    original_source_identifier: str
    s3_document_key: str = "" # Inicializa para garantir que exista
    local_temp_filepath: str = os.path.join(TEMP_FILES_DIR, str(uuid.uuid4()))
    logger.info(f"local_temp_filepath (base): {local_temp_filepath}")
    job_id: str = "" # Inicializa para garantir que exista

    try:
        if file:
            logger.info(f"Processando upload de arquivo: {file.filename}")
            original_source_identifier = file.filename
            file_extension = os.path.splitext(file.filename)[1].lower()
            local_temp_filepath += file_extension
            s3_document_key = f"textract_uploads/{uuid.uuid4()}{file_extension}"

            if file_extension not in ('.pdf', '.png', '.jpeg', '.jpg'):
                logger.error(f"Formato de arquivo não suportado: {file_extension}")
                raise HTTPException(status_code=400, detail="Formato de arquivo não suportado. Use PDF, PNG ou JPEG.")

            logger.info(f"Tentando salvar arquivo em '{local_temp_filepath}'")
            async with aiofiles.open(local_temp_filepath, 'wb') as out_file:
                while content := await file.read(1024):
                    await out_file.write(content)
            logger.info(f"Arquivo '{original_source_identifier}' salvo temporariamente em '{local_temp_filepath}'.")

        elif document_url:
            logger.info(f"Processando documento de URL: {document_url}")
            original_source_identifier = document_url
            async with httpx.AsyncClient() as client:
                logger.info(f"Tentando baixar documento da URL: {document_url}")
                response = await client.get(document_url, follow_redirects=True, timeout=30.0)
                logger.info(f"Status da resposta HTTP para URL: {response.status_code}")
                response.raise_for_status() # Levanta exceção para status 4xx/5xx
            
            content_type = response.headers.get('Content-Type', '').lower()
            logger.info(f"Content-Type da URL: {content_type}")
            if 'pdf' in content_type or document_url.lower().endswith('.pdf'):
                file_extension = '.pdf'
            elif 'png' in content_type or document_url.lower().endswith('.png'):
                file_extension = '.png'
            elif 'jpeg' in content_type or 'jpg' in content_type or document_url.lower().endswith(('.jpeg', '.jpg')):
                file_extension = '.jpg'
            else:
                logger.error(f"Não foi possível determinar o tipo de arquivo da URL: {document_url}. Content-Type: {content_type}")
                raise HTTPException(status_code=400, detail="Não foi possível determinar o tipo de arquivo da URL. Formatos suportados: PDF, PNG, JPEG.")

            local_temp_filepath += file_extension
            s3_document_key = f"textract_uploads/{uuid.uuid4()}{file_extension}"

            logger.info(f"Tentando baixar e salvar arquivo da URL em '{local_temp_filepath}'")
            async with aiofiles.open(local_temp_filepath, 'wb') as out_file:
                await out_file.write(response.content)
            logger.info(f"Arquivo de URL '{document_url}' baixado para '{local_temp_filepath}'.")

        logger.info(f"Iniciando upload para S3 para a chave: {s3_document_key}")
        await upload_file_to_s3(local_temp_filepath, s3_document_key)
        logger.info("Upload para S3 concluído.")
        
        logger.info(f"Iniciando job do Textract para a chave S3: {s3_document_key}")
        job_id = await start_textract_job(s3_document_key) 
        logger.info(f"Job do Textract iniciado com Job ID: {job_id}")

        # --- A GRANDE MUDANÇA: REMOÇÃO DO LOOP DE POLLING E RETORNO IMEDIATO ---
        logger.info(f"Job {job_id} iniciado. Retornando Job ID para o cliente. Cliente deve consultar status e resultados.")
        
        # Agendando limpeza para o arquivo local imediatamente, pois o S3 é persistente
        # A limpeza do S3 DEPOIS da conclusão do job será feita pelo endpoint de resultados.
        background_tasks.add_task(os.remove, local_temp_filepath)
        logger.info(f"Agendada exclusão do arquivo temporário local: {local_temp_filepath}")

        return JSONResponse(content={
            "message": "Análise do documento iniciada com sucesso.",
            "job_id": job_id,
            "s3_document_key": s3_document_key, # Útil para referência, mas não deve ser exposto ao cliente final se houver preocupação de segurança.
            "status_check_endpoint": f"/textract/get_analysis_status/{job_id}",
            "results_endpoint": f"/textract/get_analysis_results/{job_id}"
        }, status_code=202) # Status 202 Accepted indica que a requisição foi aceita para processamento.

    except httpx.RequestError as e:
        logger.error(f"HTTPX RequestError capturado: {str(e)}. Realizando limpeza do arquivo local se existir.", exc_info=True)
        if os.path.exists(local_temp_filepath):
            background_tasks.add_task(os.remove, local_temp_filepath)
        # Não tentamos deletar do S3 aqui, pois pode não ter sido enviado ainda
        raise HTTPException(status_code=400, detail=f"Erro ao baixar documento da URL: {e}. Verifique a URL e a conectividade.")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTPX HTTPStatusError capturado: {e.response.status_code} - {e.response.text}. Realizando limpeza do arquivo local se existir.", exc_info=True)
        if os.path.exists(local_temp_filepath):
            background_tasks.add_task(os.remove, local_temp_filepath)
        # Não tentamos deletar do S3 aqui
        raise HTTPException(status_code=e.response.status_code, detail=f"Erro HTTP ao baixar documento da URL: {e.response.status_code} - {e.response.text}. Verifique a URL.")
    except Exception as e:
        logger.error(f"Exceção INESPERADA capturada no bloco principal: {type(e).__name__}. Detalhes: {str(e)}. Realizando limpeza...", exc_info=True)
        # Limpeza é crucial aqui: se houve erro antes de retornar o job_id, o S3 pode ter ficado com o arquivo.
        if os.path.exists(local_temp_filepath):
            background_tasks.add_task(os.remove, local_temp_filepath)
        # Tenta deletar do S3 SOMENTE se s3_document_key já foi definido (ou seja, upload já ocorreu ou começou)
        if s3_document_key:
            background_tasks.add_task(delete_s3_object, s3_document_key)
            logger.info(f"Agendada exclusão do objeto S3 '{s3_document_key}' devido a erro na inicialização do job.")
        raise HTTPException(status_code=500, detail=f"Erro interno do servidor ao iniciar análise: {str(e)}. Job ID (se gerado): {job_id}")
    finally:
        logger.info("--- FIM DA EXECUÇÃO DO /analyze_document/ ---")


### **Endpoint Existente: `/get_analysis_status/{job_id}` (Mantido como está)**

@app.get("/get_analysis_status/{job_id}", summary="Verifica o status de um trabalho de análise do Textract")
async def get_analysis_status(job_id: str):
    """
    Verifica o status atual de um trabalho de análise do Textract
    dado o Job ID.
    """
    logger.info(f"--- INÍCIO DA EXECUÇÃO DO /get_analysis_status/{job_id} ---")
    try:
        current_status, _ = await is_job_complete(job_id)
        logger.info(f"Status do job {job_id} obtido do Textract: {current_status}")
        return JSONResponse(content={"job_id": job_id, "status": current_status})
    except HTTPException as e:
        logger.error(f"HTTPException em /get_analysis_status/: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Exceção inesperada em /get_analysis_status/: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao verificar status do job: {e}")
    finally:
        logger.info(f"--- FIM DA EXECUÇÃO DO /get_analysis_status/{job_id} ---")


### **Endpoint Existente: `/get_analysis_results/{job_id}` (Agora é responsável pela limpeza final do S3)**

@app.get("/get_analysis_results/{job_id}", summary="Obtém o texto limpo de um trabalho de análise do Textract")
async def get_analysis_results(job_id: str, background_tasks: BackgroundTasks):
    """
    Obtém o texto extraído limpo de um trabalho de análise do Textract
    dado o Job ID. **Este endpoint ainda fará o polling interno** se o job estiver
    em andamento, mas o cliente será o responsável por chamá-lo apenas quando
    o status for SUCCEEDED (ou se quiser que ele espere).
    Retorna apenas o texto limpo, sem caracteres inválidos para SQL Server.
    **ATENÇÃO:** Este endpoint é responsável por AGENDAR a exclusão do objeto S3
    após a obtenção dos resultados para liberar espaço e dados sensíveis.
    """
    logger.info(f"--- INÍCIO DA EXECUÇÃO DO /get_analysis_results/{job_id} ---")
    s3_document_key: str = "" # Necessário inicializar para o bloco finally

    try:
        current_status = "IN_PROGRESS"
        logger.info(f"Verificando status do job {job_id} para obter resultados...")
        start_time_dt = datetime.now() # Adicionado para medir a duração total da espera E processamento

        # Adicionei um limite de tempo para este polling interno para evitar que este endpoint bloqueie por horas
        # Idealmente, o cliente chamaria `get_analysis_status` primeiro.
        # Ajuste `max_wait_seconds` conforme sua necessidade de tolerância.
        max_wait_seconds = 600 # Exemplo: 10 minutos de espera máxima neste endpoint
        wait_start_time = time.monotonic()

        while current_status == 'IN_PROGRESS':
            if time.monotonic() - wait_start_time > max_wait_seconds:
                logger.warning(f"Timeout de espera excedido ({max_wait_seconds}s) para o job {job_id} no endpoint /get_analysis_results/. Status: {current_status}")
                raise HTTPException(status_code=504, detail=f"Tempo limite excedido aguardando conclusão do job {job_id}. Tente consultar o status novamente mais tarde.")

            status_response, original_s3_key = await is_job_complete(job_id)
            current_status = status_response
            s3_document_key = original_s3_key # Captura a chave S3 aqui
            if current_status == 'IN_PROGRESS':
                logger.info(f"Job {job_id} ainda em andamento. Aguardando para obter resultados em 5 segundos...")
                await asyncio.sleep(5)

        end_time_dt = datetime.now()
        duration_seconds = (end_time_dt - start_time_dt).total_seconds()
        formatted_duration = format_duration(duration_seconds)
        logger.info(f"Job {job_id} concluído com status: {current_status}. Duração da espera (se houver): {formatted_duration}")


        if current_status == 'SUCCEEDED':
            logger.info(f"Job {job_id} bem-sucedido. Recuperando e processando resultados...")
            textract_pages_data = await get_job_results(job_id)
            all_lines = extract_lines_from_textract_response(textract_pages_data)
            
            full_extracted_text = "\n".join(all_lines)
            cleaned_text = sanitize_text_for_sql(full_extracted_text)
            logger.info(f"Resultados para job {job_id} obtidos e texto limpo.")
            
            # --- LIMPEZA DO S3 AGORA ACONTECE AQUI ---
            if s3_document_key: # Garante que a chave S3 foi obtida
                background_tasks.add_task(delete_s3_object, s3_document_key)
                logger.info(f"Agendada exclusão do objeto S3 '{s3_document_key}' para o job {job_id}.")
            else:
                logger.warning(f"Não foi possível obter s3_document_key para o job {job_id} para agendar a limpeza do S3.")


            return JSONResponse(content={"job_id": job_id, "cleaned_text": cleaned_text})
        else:
            logger.error(f"Job {job_id} não foi bem-sucedido. Status: {current_status}.")
            # Se o job falhou, ainda tentamos limpar o S3, se a chave estiver disponível
            if s3_document_key:
                background_tasks.add_task(delete_s3_object, s3_document_key)
                logger.info(f"Agendada exclusão do objeto S3 '{s3_document_key}' para o job {job_id} que falhou.")

            raise HTTPException(status_code=500, detail=f"A análise do documento falhou. Status: {current_status}. Job ID: {job_id}")

    except HTTPException as e:
        logger.error(f"HTTPException em /get_analysis_results/: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Exceção inesperada em /get_analysis_results/: {str(e)}", exc_info=True)
        # Se houve uma exceção genérica aqui, e o s3_document_key foi obtido
        if s3_document_key:
            background_tasks.add_task(delete_s3_object, s3_document_key)
            logger.info(f"Agendada exclusão do objeto S3 '{s3_document_key}' devido a erro na obtenção dos resultados do job {job_id}.")
        raise HTTPException(status_code=500, detail=f"Erro ao obter resultados do job: {e}")
    finally:
        logger.info(f"--- FIM DA EXECUÇÃO DO /get_analysis_results/{job_id} ---")