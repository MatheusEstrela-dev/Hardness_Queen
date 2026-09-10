"""Etapa 01: gera os exemplos de treino do adaptador que redige alertas.

CLI fina sobre ingestao/dataset.py -- a logica vive la para poder ser testada
sem truque de import: este arquivo tem ponto no nome e nao e importavel.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.dataset import gerar

if __name__ == "__main__":
    gerar()
