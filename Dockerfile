# Usa uma imagem base oficial do Python. Escolha uma versão 3.7+
# Python 3.9 é uma boa escolha, balanceando modernidade e estabilidade.
FROM python:3.9-slim-buster

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copia o arquivo requirements.txt para o contêiner
# e instala as dependências. Isso aproveita o cache do Docker.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código da sua aplicação para o diretêrio de trabalho
COPY . .

# Expõe a porta que sua aplicação vai ouvir
EXPOSE 8000

# Comando para iniciar sua aplicação com Gunicorn quando o contêiner for iniciado
# Certifique-se que o "main:app" e as opções do Gunicorn estão corretas
CMD ["gunicorn", "main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--log-level", "info"]

