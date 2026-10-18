import threading

from app.aplicacao.executar_carga import (
    CATALOGO_ETAPAS,
    ErroRequisicao,
    OrquestradorCargas,
    validar_pedido,
)


class RepositorioFake:
    def __init__(self, lock_disponivel=True):
        self.lock_disponivel = lock_disponivel
        self.concluido = threading.Event()
        self.etapas = []
        self.status_final = None
        self.lock = object()

    def adquirir_lock(self):
        return self.lock if self.lock_disponivel else None

    def liberar_lock(self, _lock):
        pass

    def em_andamento(self):
        return {"id": "execucao-atual"}

    def criar(self, *_args):
        pass

    def iniciar(self, *_args):
        pass

    def iniciar_etapa(self, _id, _ordem, etapa):
        self.etapas.append(etapa)

    def finalizar_etapa(self, *_args):
        pass

    def finalizar(self, _id, status, *_args):
        self.status_final = status
        self.concluido.set()

    def falha_antes_das_etapas(self, _id, erro):
        self.status_final = f"FALHA:{erro}"
        self.concluido.set()


def test_parcial_valida_etapas_e_normaliza_ordem_do_catalogo():
    pedido = validar_pedido({
        "tipo": "PARCIAL", "etapas": ["DVA", "COTAHIST"], "solicitada_por": "PAINEL"
    })

    assert pedido.etapas == ("COTAHIST", "DVA")


def test_rejeita_etapa_fora_do_catalogo():
    try:
        validar_pedido({"tipo": "PARCIAL", "etapas": ["MIGRATION"]})
    except ErroRequisicao as erro:
        assert "não reconhecida" in str(erro)
    else:
        raise AssertionError("etapa desconhecida deveria ser rejeitada")


def test_rotina_usa_catalogo_sem_eventos_e_janelas_historicas_corretas():
    repo = RepositorioFake()
    orquestrador = OrquestradorCargas(repo, {etapa: lambda *_: {} for etapa in CATALOGO_ETAPAS})
    pedido = validar_pedido({"tipo": "ROTINA"})

    anos_por_etapa = orquestrador._resolver_execucao(pedido)

    assert "EVENTOS" not in anos_por_etapa
    assert len(anos_por_etapa["DFP"]) == 2
    assert len(anos_por_etapa["TTM"]) == 1


def test_disparo_persiste_etapas_e_responde_aceito():
    repo = RepositorioFake()
    catalogo = {etapa: lambda *_: {} for etapa in CATALOGO_ETAPAS}
    orquestrador = OrquestradorCargas(repo, catalogo)

    codigo, corpo = orquestrador.disparar({"tipo": "PARCIAL", "etapas": ["DFP"]})

    assert codigo == 202
    assert corpo["status"] == "PENDENTE"
    assert repo.concluido.wait(2)
    assert repo.etapas == ["DFP"]
    assert repo.status_final == "SUCESSO"


def test_disparo_concorrente_retorna_409_com_execucao_atual():
    repo = RepositorioFake(lock_disponivel=False)
    orquestrador = OrquestradorCargas(repo, {})

    codigo, corpo = orquestrador.disparar({"tipo": "ROTINA"})

    assert codigo == 409
    assert corpo == {"execucao_em_andamento": "execucao-atual"}
