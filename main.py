# Importações necessárias
import boto3
import time
import json
import os
import re
import uuid # Adicionado para uuid.uuid4()
import aiofiles # Adicionado para aiofiles.open
import httpx # Adicionado para httpx.AsyncClient
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import HTMLResponse, JSONResponse # Importação corrigida para HTMLResponse e JSONResponse

# Importa as funções e clientes dos novos módulos
from textract_service.aws_clients import S3_BUCKET_NAME, textract_client, s3_client
from textract_service.textract_logic import start_textract_job, is_job_complete, get_job_results, extract_lines_from_textract_response
from textract_service.s3_operations import upload_file_to_s3, delete_s3_object, get_file_size_mb
from utils.text_sanitizer import sanitize_text_for_sql

# Inicializa a aplicação FastAPI
app = FastAPI(
    title="AWS Textract Document Analysis API",
    description="API para analisar documentos PDF/Imagens usando AWS Textract, com upload direto e retorno de resultados.",
    version="1.0.0"
)

# --- Configuração do Diretório Temporário ---
# IMPORTANTE: Garanta que o usuário que executa esta aplicação tenha permissões de escrita neste diretório.
# Em Linux, /tmp é um diretório comum, mas /var/tmp ou um diretório específico da aplicação pode ser melhor.
TEMP_FILES_DIR = os.getenv("TEMP_FILES_DIR", "/tmp") # Pega do ENV ou usa /tmp como padrão

# --- Funções Auxiliares Comuns ---

def format_duration(seconds: float) -> str:
    """Formata a duração em HH:MM:SS.millis."""
    millis = int((seconds - int(seconds)) * 1000)
    h = int((seconds % 3600) // 60)
    m = int(seconds % 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}.{millis:03}"

# --- Endpoints da FastAPI ---

@app.get("/", response_class=HTMLResponse, summary="Página inicial")
async def read_root():
    """Retorna uma página HTML simples para a raiz da API."""
    return """
    <html>
        <head>
            <title>AWS Textract API</title>
        </head>
        <body>
            <h1>Bem-vindo à API de Análise de Documentos com AWS Textract</h1>
            <p>Use o endpoint <code>/analyze_document/</code> para enviar um documento ou fornecer uma URL e obter o texto direto.</p>
            <p>Os endpoints de status e resultados separados são para referência em ambientes persistentes.</p>
            <p>Você pode testar a API através da interface Swagger UI em <a href="/docs">/docs</a> ou ReDoc em <a href="/redoc">/redoc</a>.</p>
        </body>
    </html>
    """

@app.post("/analyze_document/", summary="Analisa um documento PDF/Imagem enviado ou de uma URL e retorna o texto extraído diretamente")
async def analyze_document(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None, description="O documento (PDF, JPEG, PNG) a ser analisado (upload)."),
    document_url: Optional[str] = Form(None, description="URL de onde o documento (PDF, JPEG, PNG) será baixado.")
):
    """
    Recebe um arquivo de documento via upload ou uma URL, faz o download/upload para S3,
    inicia um trabalho de análise com AWS Textract, aguarda a conclusão e retorna o texto limpo.
    Um dos dois parâmetros (file ou document_url) deve ser fornecido.
    """
    print("--- INÍCIO DA EXECUÇÃO DO /analyze_document/ ---")
    if not file and not document_url:
        print("Erro: Nenhum arquivo ou URL fornecido.")
        raise HTTPException(status_code=400, detail="Por favor, forneça um arquivo ou uma URL de documento.")
    if file and document_url:
        print("Erro: Ambos arquivo e URL fornecidos.")
        raise HTTPException(status_code=400, detail="Forneça apenas um: arquivo ou URL de documento, não ambos.")

    file_extension: str
    original_source_identifier: str # Identifica se veio de arquivo ou URL
    s3_document_key: str
    # Constrói o caminho temporário usando o diretório configurado
    local_temp_filepath: str = os.path.join(TEMP_FILES_DIR, str(uuid.uuid4()))
    print(f"local_temp_filepath (base): {local_temp_filepath}")
    job_id: str = "" # Inicializa job_id para garantir que esteja definido

    try:
        if file:
            print(f"Processando upload de arquivo: {file.filename}")
            original_source_identifier = file.filename
            file_extension = os.path.splitext(file.filename)[1].lower()
            local_temp_filepath += file_extension # Adiciona extensão ao caminho temporário
            s3_document_key = f"textract_uploads/{uuid.uuid4()}{file_extension}"

            if file_extension not in ('.pdf', '.png', '.jpeg', '.jpg'):
                print(f"Erro: Formato de arquivo não suportado: {file_extension}")
                raise HTTPException(status_code=400, detail="Formato de arquivo não suportado. Use PDF, PNG ou JPEG.")

            # Salva o arquivo enviado localmente (temporariamente)
            print(f"Tentando salvar arquivo em '{local_temp_filepath}'")
            async with aiofiles.open(local_temp_filepath, 'wb') as out_file:
                while content := await file.read(1024):  # Lê em chunks
                    await out_file.write(content)
            print(f"Arquivo '{original_source_identifier}' salvo temporariamente em '{local_temp_filepath}'.")

        elif document_url:
            print(f"Processando documento de URL: {document_url}")
            original_source_identifier = document_url # Para fins de registro, usa a URL como "nome original"
            async with httpx.AsyncClient() as client:
                print(f"Tentando baixar documento da URL: {document_url}")
                response = await client.get(document_url, follow_redirects=True, timeout=30.0)
                print(f"Status da resposta HTTP para URL: {response.status_code}")
                response.raise_for_status() # Lança HTTPException para 4xx/5xx responses
            
            # Tenta inferir a extensão do arquivo da URL ou do cabeçalho Content-Type
            content_type = response.headers.get('Content-Type', '').lower()
            print(f"Content-Type da URL: {content_type}")
            if 'pdf' in content_type or document_url.lower().endswith('.pdf'):
                file_extension = '.pdf'
            elif 'png' in content_type or document_url.lower().endswith('.png'):
                file_extension = '.png'
            elif 'jpeg' in content_type or 'jpg' in content_type or document_url.lower().endswith(('.jpeg', '.jpg')):
                file_extension = '.jpg'
            else:
                print(f"Erro: Não foi possível determinar o tipo de arquivo da URL: {document_url}. Content-Type: {content_type}")
                raise HTTPException(status_code=400, detail="Não foi possível determinar o tipo de arquivo da URL. Formatos suportados: PDF, PNG, JPEG.")

            local_temp_filepath += file_extension
            s3_document_key = f"textract_uploads/{uuid.uuid4()}{file_extension}"

            print(f"Tentando baixar e salvar arquivo da URL em '{local_temp_filepath}'")
            async with aiofiles.open(local_temp_filepath, 'wb') as out_file:
                await out_file.write(response.content)
            print(f"Arquivo de URL '{document_url}' baixado para '{local_temp_filepath}'.")

        # 2. Faz o upload do arquivo temporário para o S3
        print(f"Iniciando upload para S3 para a chave: {s3_document_key}")
        await upload_file_to_s3(local_temp_filepath, s3_document_key)
        print("Upload para S3 concluído.")
        
        # 3. Inicia o trabalho do Textract
        print(f"Iniciando job do Textract para a chave S3: {s3_document_key}")
        job_id = start_textract_job(s3_document_key) 
        print(f"Job do Textract iniciado com Job ID: {job_id}")

        # --- LÓGICA DE ESPERA E OBTENÇÃO DE RESULTADOS SÍNCRONA ---
        current_status = "IN_PROGRESS"
        start_time_dt = datetime.now()
        print("Aguardando conclusão do job do Textract...")

        while current_status == 'IN_PROGRESS':
            status_response, _ = is_job_complete(job_id)
            current_status = status_response
            if current_status == 'IN_PROGRESS':
                print(f"Job {job_id} ainda em andamento. Verificando novamente em 5 segundos...")
                time.sleep(5) # Espera 5 segundos antes de verificar novamente

        end_time_dt = datetime.now()
        duration_seconds = (end_time_dt - start_time_dt).total_seconds()
        formatted_duration = format_duration(duration_seconds)
        print(f"Job {job_id} concluído com status: {current_status}. Duração: {formatted_duration}")

        if current_status == 'SUCCEEDED':
            print(f"Job {job_id} bem-sucedido. Obtendo resultados...")
            textract_pages_data = get_job_results(job_id)
            all_lines = extract_lines_from_textract_response(textract_pages_data)
            
            full_extracted_text = "\n".join(all_lines)
            cleaned_text = sanitize_text_for_sql(full_extracted_text)
            print("Texto extraído e sanitizado com sucesso.")
            
            # Limpa o arquivo S3 e local em background após o processamento
            background_tasks.add_task(delete_s3_object, s3_document_key)
            background_tasks.add_task(os.remove, local_temp_filepath)
            print("Tarefas de limpeza (S3 e local) agendadas em segundo plano.")

            return JSONResponse(content={
                "job_id": job_id,
                "status": current_status,
                "duration": formatted_duration,
                "cleaned_text": cleaned_text
            }, status_code=200)
        else:
            # Se o job falhou, limpa o S3 e o arquivo local
            background_tasks.add_task(delete_s3_object, s3_document_key)
            background_tasks.add_task(os.remove, local_temp_filepath)
            print(f"Job {job_id} falhou com status: {current_status}. Tarefas de limpeza agendadas.")
            raise HTTPException(status_code=500, detail=f"A análise do documento falhou. Status: {current_status}. Job ID: {job_id}")

    except httpx.RequestError as e:
        print(f"HTTPX RequestError capturado: {e}. Realizando limpeza...")
        if os.path.exists(local_temp_filepath):
            background_tasks.add_task(os.remove, local_temp_filepath)
        raise HTTPException(status_code=400, detail=f"Erro ao baixar documento da URL: {e}")
    except httpx.HTTPStatusError as e:
        print(f"HTTPX HTTPStatusError capturado: {e.response.status_code} - {e.response.text}. Realizando limpeza...")
        if os.path.exists(local_temp_filepath):
            background_tasks.add_task(os.remove, local_temp_filepath)
        raise HTTPException(status_code=e.response.status_code, detail=f"Erro HTTP ao baixar documento da URL: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        # CORREÇÃO: Imprimir a string da exceção
        print(f"Exceção INESPERADA capturada no bloco principal: {type(e).__name__}. Detalhes: {str(e)}. Realizando limpeza...")
        # Limpeza em caso de qualquer outra exceção inesperada
        if os.path.exists(local_temp_filepath):
            background_tasks.add_task(os.remove, local_temp_filepath)
        if job_id and s3_document_key: # Verifica se s3_document_key foi definido
            background_tasks.add_task(delete_s3_object, s3_document_key)
        raise HTTPException(status_code=500, detail=f"Erro interno do servidor: {str(e)}. Job ID: {job_id}")
    finally:
        print("--- FIM DA EXECUÇÃO DO /analyze_document/ ---")


@app.get("/get_analysis_status/{job_id}", summary="Verifica o status de um trabalho de análise do Textract")
async def get_analysis_status(job_id: str):
    """
    Verifica o status atual de um trabalho de análise do Textract
    dado o Job ID.

    Este endpoint é mantido para compatibilidade, mas não funciona mais
    para jobs históricos após um restart, pois o estado não é persistente.
    """
    print(f"--- INÍCIO DA EXECUÇÃO DO /get_analysis_status/{job_id} ---")
    try:
        current_status, _ = is_job_complete(job_id)
        print(f"Status do job {job_id} obtido do Textract: {current_status}")
        # Não há armazenamento em memória, então apenas retorna o status atual diretamente do Textract
        return JSONResponse(content={"job_id": job_id, "status": current_status})
    except HTTPException as e:
        print(f"HTTPException em /get_analysis_status/: {e.detail}")
        raise e
    except Exception as e:
        print(f"Exceção inesperada em /get_analysis_status/: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao verificar status do job: {e}")
    finally:
        print(f"--- FIM DA EXECUÇÃO DO /get_analysis_status/{job_id} ---")


@app.get("/get_analysis_results/{job_id}", summary="Obtém o texto limpo de um trabalho de análise do Textract")
async def get_analysis_results(job_id: str, background_tasks: BackgroundTasks):
    """
    Obtém o texto extraído limpo de um trabalho de análise do Textract
    dado o Job ID. Aguarda a conclusão se o job ainda estiver em andamento.
    Retorna apenas o texto limpo, sem caracteres inválidos para SQL Server.

    Este endpoint é mantido para compatibilidade, mas não funciona mais
    para jobs históricos após um restart, pois o estado não é persistente.
    """
    print(f"--- INÍCIO DA EXECUÇÃO DO /get_analysis_results/{job_id} ---")
    try:
        # Aguarda a conclusão do job, se necessário
        current_status = "IN_PROGRESS"
        print(f"Verificando status do job {job_id} para obter resultados...")
        while current_status == 'IN_PROGRESS':
            status_response, _ = is_job_complete(job_id)
            current_status = status_response
            if current_status == 'IN_PROGRESS':
                print(f"Job {job_id} ainda em andamento. Aguardando para obter resultados...")
                time.sleep(5)

        if current_status == 'SUCCEEDED':
            print(f"Job {job_id} bem-sucedido. Recuperando e processando resultados...")
            textract_pages_data = get_job_results(job_id)
            all_lines = extract_lines_from_textract_response(textract_pages_data)
            
            full_extracted_text = "\n".join(all_lines)
            cleaned_text = sanitize_text_for_sql(full_extracted_text)
            print(f"Resultados para job {job_id} obtidos e texto limpo.")
            
            # Não há s3_key armazenada em memória para limpeza automática aqui.
            # Se você precisar da limpeza aqui, o s3_key precisaria ser passado ou buscado.
            # Neste fluxo, a limpeza é responsabilidade do analyze_document para jobs síncronos.
            
            return JSONResponse(content={"job_id": job_id, "cleaned_text": cleaned_text})
        else:
            print(f"Job {job_id} não foi bem-sucedido. Status: {current_status}.")
            raise HTTPException(status_code=500, detail=f"A análise do documento falhou. Status: {current_status}. Job ID: {job_id}")
    except HTTPException as e:
        print(f"HTTPException em /get_analysis_results/: {e.detail}")
        raise e
    except Exception as e:
        print(f"Exceção inesperada em /get_analysis_results/: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter resultados do job: {e}")
    finally:
        print(f"--- FIM DA EXECUÇÃO DO /get_analysis_results/{job_id} ---")