AWS Textract FastAPI - Análise de Documentos
Visão Geral do Projeto
Este projeto implementa uma API RESTful usando FastAPI para interagir com o serviço AWS Textract. Ele permite que os usuários enviem documentos (PDF, JPEG, PNG) via upload direto ou através de uma URL, processem-nos de forma síncrona com o Textract (aguardando a conclusão da análise) e obtenham o texto extraído e sanitizado para armazenamento em bancos de dados SQL.

O principal objetivo desta API é fornecer uma interface simplificada para aproveitar os recursos avançados de reconhecimento de texto, tabelas, formulários e assinaturas do AWS Textract, abstraindo a complexidade do gerenciamento de S3 e do fluxo de trabalho assíncrono (do ponto de vista do cliente).

Funcionalidades
Upload de Documentos: Aceita arquivos PDF, JPEG e PNG via upload HTTP.

Download de Documentos por URL: Permite que a API baixe e processe documentos de uma URL fornecida.

Análise Síncrona com AWS Textract: O endpoint principal aguarda a conclusão do StartDocumentAnalysis do Textract e retorna os resultados diretamente, adequado para arquivos que precisam de retorno imediato.

Gerenciamento Temporário de S3: Faz o upload dos documentos para um bucket S3 temporário para processamento pelo Textract e os remove automaticamente após a extração dos resultados e retorno para o cliente.

Extração de Texto Limpo: Retorna o texto extraído do documento, removendo caracteres inválidos e substituindo quebras de linha por espaços para compatibilidade com bancos de dados SQL (como o SQL Server).

Estrutura Organizada: Código dividido em módulos para melhor organização e manutenibilidade.

Pré-requisitos
Antes de executar este projeto, certifique-se de ter o seguinte:

Python 3.8+: Baixe e instale a versão mais recente do Python.

Conta AWS: Você precisa de uma conta AWS ativa.

Credenciais AWS Configuradas: Suas credenciais AWS devem estar configuradas no ambiente onde a aplicação será executada. As formas mais comuns incluem:

Variáveis de ambiente: AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY.

Arquivo de credenciais: ~/.aws/credentials (Linux/macOS) ou %USERPROFILE%\.aws\credentials (Windows).

Perfis IAM (se executando em EC2, Lambda, EKS, etc.).

Bucket S3: Um bucket S3 na sua conta AWS. Este bucket será usado para carregar temporariamente os documentos para o Textract.

Instalação
Clone o Repositório (se aplicável, ou crie a estrutura de pastas manualmente e adicione os arquivos).

git clone <URL_DO_SEU_REPOSITORIO>
cd textract-api

Crie e Ative um Ambiente Virtual (recomendado para gerenciar dependências).

python -m venv venv
# No Windows
.\venv\Scripts\activate
# No Linux/macOS
source venv/bin/activate

Instale as Dependências:

pip install -r requirements.txt

Configuração
Configure o Bucket S3:
Abra o arquivo textract_service/aws_clients.py e substitua "teste-textract-conrado" pelo nome do seu bucket S3:

# textract_service/aws_clients.py

# ...
S3_BUCKET_NAME = "seu-nome-do-bucket-s3" # <--- SUBSTITUA AQUI
# ...

Certifique-se de que o IAM (Identity and Access Management) da sua conta AWS tenha as permissões necessárias para o Textract (textract:*) e para as operações de S3 (s3:GetObject, s3:PutObject, s3:DeleteObject).

Como Executar
No diretório raiz do projeto (textract-api/), execute o aplicativo FastAPI usando Uvicorn:

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

--host 0.0.0.0: Torna a API acessível de outras máquinas na sua rede (se necessário).

--port 8000: Define a porta em que a API será executada.

--reload: Reinicia o servidor automaticamente a cada alteração no código-fonte (útil para desenvolvimento).

Uma vez que a aplicação estiver em execução, você poderá acessá-la em http://127.0.0.1:8000 (ou o endereço IP do seu servidor).

Uso da API
A FastAPI gera automaticamente uma documentação interativa (Swagger UI) e uma documentação Redoc.

Swagger UI: http://127.0.0.1:8000/docs

Redoc: http://127.0.0.1:8000/redoc

Endpoints Disponíveis
1. GET /
Descrição: Página inicial simples da API.

Retorno: Conteúdo HTML básico.

2. POST /analyze_document/
Descrição: Inicia o processo de análise de um documento usando o AWS Textract. Você deve fornecer um arquivo (upload) ou uma URL. A API aguardará a conclusão da análise e retornará o texto extraído diretamente.

Parâmetros:

file (opcional, UploadFile): O documento (PDF, JPEG, PNG) a ser analisado via upload.

document_url (opcional, string): A URL de onde o documento (PDF, JPEG, PNG) será baixado.

Observações:

Apenas um dos dois parâmetros (file ou document_url) deve ser fornecido.

A API fará o upload do documento para o S3, iniciará um trabalho no Textract, aguardará sua conclusão e retornará os resultados.

Retorno (Status 200 OK):

{
    "job_id": "seu_job_id_unico_aqui",
    "cleaned_text": "Texto extraído do seu documento, já limpo para SQL Server e sem quebras de linha."
}

3. GET /get_analysis_status/{job_id}
Descrição: Verifica o status atual de um trabalho de análise do Textract. Este endpoint é mantido para compatibilidade, embora o /analyze_document/ agora espere pela conclusão. Ele busca o status diretamente do AWS Textract.

Parâmetros:

job_id (obrigatório, string): O ID do trabalho retornado pelo endpoint /analyze_document/.

Retorno (Status 200 OK):

{
    "job_id": "seu_job_id_unico_aqui",
    "status": "IN_PROGRESS" # Pode ser "IN_PROGRESS", "SUCCEEDED", "FAILED"
}

4. GET /get_analysis_results/{job_id}
Descrição: Obtém o texto extraído e limpo de um trabalho de análise do Textract. Este endpoint é mantido para compatibilidade e pode ser útil para re-obter resultados de um job previamente processado (se o job ainda for válido no Textract).

Parâmetros:

job_id (obrigatório, string): O ID do trabalho retornado pelo endpoint /analyze_document/.

Retorno (Status 200 OK):

{
    "job_id": "seu_job_id_unico_aqui",
    "cleaned_text": "Texto extraído do seu documento, já limpo para SQL Server e sem quebras de linha."
}

Observações:

Após a entrega do cleaned_text pelo /analyze_document/, o documento temporário no S3 será deletado automaticamente (em segundo plano) para limpeza.

Exemplo de Fluxo (Usando curl ou um cliente HTTP)
1. Iniciar Análise (Upload de Arquivo) - Agora retorna o texto diretamente:

curl -X POST "http://127.0.0.1:8000/analyze_document/" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@/caminho/para/seu/documento.pdf"

2. Iniciar Análise (Via URL) - Agora retorna o texto diretamente:

curl -X POST "http://127.0.0.1:8000/analyze_document/" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "document_url=https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"

3. Verificar Status (Opcional):

curl "http://127.0.0.1:8000/get_analysis_status/seu_job_id_unico_aqui"

4. Obter Resultados (Opcional, se o status for SUCCEEDED):

curl "http://127.0.0.1:8000/get_analysis_results/seu_job_id_unico_aqui"

Boas Práticas e Escalabilidade
Gerenciamento de Estado: Atualmente, o estado dos jobs não é persistente entre reinícios da aplicação (dicionário em memória removido). Para persistência e escalabilidade em um ambiente de produção (onde a API pode ter várias instâncias ou ser reiniciada), você deve integrar um banco de dados (como DynamoDB, Redis, PostgreSQL ou similar) para armazenar o estado dos jobs.

Segurança: Para produção, considere implementar autenticação e autorização para proteger seus endpoints da API (ex: OAuth2, API Keys).

Logging: Adicione um sistema de logging mais robusto para monitorar a aplicação e depurar problemas em produção.

Tratamento de Erros: O tratamento de erros atual é básico. Em um ambiente de produção, você pode querer implementar um tratamento de erros mais granular e customizado.

Variáveis de Ambiente: As configurações da AWS (como S3_BUCKET_NAME e AWS_REGION) estão atualmente codificadas no arquivo aws_clients.py. Para um ambiente de produção, é uma boa prática usar variáveis de ambiente (por exemplo, com a biblioteca python-dotenv) para gerenciar essas configurações.

Licença
Este projeto é de código aberto e está disponível sob a licença MIT.


gunicorn main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8002 --log-level info