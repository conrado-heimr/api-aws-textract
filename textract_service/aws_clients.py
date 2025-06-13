#textract_service/aws_clients.py
import boto3
from botocore.config import Config

# Configurações do AWS S3 e Textract
# ATENÇÃO: Substitua 'YOUR_S3_BUCKET_NAME' pelo nome do seu bucket S3.
# Certifique-se de que as credenciais AWS estão configuradas no ambiente
# (variáveis de ambiente, ~/.aws/credentials, etc.)
AWS_REGION = "us-east-1"
S3_BUCKET_NAME = "teste-textract-conrado" 

# Configuração de timeout para o Boto3
# Conexão: 60 segundos
# Leitura/Resposta: 1800 segundos (30 minutos)
# Retentativas: 10 vezes
boto3_config = Config(
    connect_timeout=60,
    read_timeout=1800, # MUITO IMPORTANTE para documentos grandes!
    retries={'max_attempts': 10}
)

# Inicializa a sessão Boto3
# Certifique-se de que as credenciais AWS estão configuradas no ambiente de execução da aplicação
# (via variáveis de ambiente AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN, 
#  ou via arquivo ~/.aws/credentials, ou perfis IAM em EC2/ECS).
session = boto3.Session(region_name=AWS_REGION) # Passa a região para a sessão

# Inicializa os clientes AWS para Textract e S3 a partir da sessão
# Estes clientes serão usados em toda a aplicação
textract_client = session.client('textract') # Não precisa repetir region_name aqui
s3_client = session.client('s3') # Não precisa repetir region_name aqui

# Para uso em outros módulos
__all__ = ['textract_client', 's3_client', 'S3_BUCKET_NAME']

