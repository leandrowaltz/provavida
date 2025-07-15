# Use uma imagem Python oficial como base. A versão 'slim' é menor.
FROM python:3.9-slim-buster

# Instala as dependências do sistema para a biblioteca 'locale' em pt_BR
# Isso é necessário para a formatação correta de datas em português nos PDFs.
RUN apt-get update && apt-get install -y locales && \
    sed -i -e 's/# pt_BR.UTF-8 UTF-8/pt_BR.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales

# Define as variáveis de ambiente de localização para toda a imagem
ENV LANG pt_BR.UTF-8
ENV LANGUAGE pt_BR:pt
ENV LC_ALL pt_BR.UTF-8

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código da aplicação (app.py) para o diretório de trabalho
COPY . .

# Expõe a porta em que o Gunicorn irá rodar
EXPOSE 5000

# Comando para iniciar a aplicação em produção usando Gunicorn
# Ele irá procurar pela variável 'app' no arquivo 'app.py'
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
