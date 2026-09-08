def test_pacote_ingestao_importavel():
    import ingestao

    assert ingestao is not None


def test_stack_de_treino_intacto():
    import transformers
    import trl

    assert transformers.__version__.startswith("5.")
    assert trl.__version__.startswith("1.")
