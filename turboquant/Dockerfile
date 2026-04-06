FROM nvidia/cuda:12.6.2-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    git \
    build-essential \
    libpcre3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python3 /usr/bin/python

RUN pip3 install --upgrade pip setuptools wheel

RUN pip3 install torch torchaudio --index-url https://download.pytorch.org/whl/cu126

# ninja acelera compilação de extensões CUDA
RUN pip3 install ninja

# pcre não existe no PyPI — cria stub que delega ao módulo re nativo
RUN python3 -c "open('/usr/local/lib/python3.10/dist-packages/pcre.py','w').write('from re import *\n')"

WORKDIR /tmp

# copia script de patch
COPY turboquant/patch_gptq.py /tmp/patch_gptq.py

# baixa o tarball diretamente via PyPI JSON API — sem acionar hooks do pyproject.toml
RUN python3 -c "\
import urllib.request, json; \
data = json.loads(urllib.request.urlopen('https://pypi.org/pypi/gptqmodel/6.0.3/json').read()); \
url = next(u['url'] for u in data['urls'] if u['filename'].endswith('.tar.gz')); \
urllib.request.urlretrieve(url, '/tmp/gptqmodel-6.0.3.tar.gz')"

RUN pip3 install -U setuptools && \
    tar xzf /tmp/gptqmodel-6.0.3.tar.gz && \
    cd /tmp/gptqmodel-6.0.3 && \
    rm -f pyproject.toml && \
    python3 /tmp/patch_gptq.py && \
    export MAX_JOBS=1 TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0" CUDA_ARCH_LIST="8.0;8.6;8.9;9.0" && \
    python3 setup.py install && \
    rm -rf /tmp/gptqmodel-6.0.3 /tmp/gptqmodel-6.0.3.tar.gz

# patch pós-install: exllamav3_torch.py usa tensor no nível do módulo — falha
# quando importado dentro do contexto meta-device do transformers (from_pretrained)
# struct.unpack('e',...) dá o mesmo resultado sem criar tensores
RUN python3 -c "\
p='/usr/local/lib/python3.10/dist-packages/gptqmodel/nn_modules/exllamav3_torch.py'; \
t=open(p).read(); \
f=t.replace('return float(torch.tensor([bits], dtype=torch.uint16).view(torch.float16).item())','import struct; return struct.unpack(chr(101), struct.pack(chr(72), bits))[0]'); \
assert f!=t,'pattern not found'; open(p,'w').write(f); print('patched')"

# dependências de runtime do gptqmodel (não instaladas pelo setup.py install)
# pypcre substitui o stub pcre.py em runtime (a .so tem prioridade sobre .py)
RUN pip3 install \
    logbar \
    pypcre \
    threadpoolctl \
    device-smi \
    pillow \
    tokenicer \
    defuser \
    kernels \
    torchao \
    datasets \
    dill \
    pyarrow

# autoawq usa --no-build-isolation para enxergar o torch já instalado
RUN pip3 install autoawq --no-build-isolation

RUN pip3 install turboquant transformers accelerate

WORKDIR /workspace

# Variáveis configuráveis via docker-compose environment
ENV TURBOQUANT_MODEL="Qwen/Qwen2.5-7B-Instruct-AWQ"
ENV TURBOQUANT_BITS=3
ENV TURBOQUANT_PORT=8000
ENV TURBOQUANT_CTX=512

EXPOSE 8000

CMD ["sh", "-c", "turboquant-server --model \"$TURBOQUANT_MODEL\" --bits \"$TURBOQUANT_BITS\" --port \"$TURBOQUANT_PORT\" --max-model-len $TURBOQUANT_CTX"]
