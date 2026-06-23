OPCIONES_POR_PAGINA = ['5', '10', '25', '50', '100']


def obtener_por_pagina(request, parametro='per_page', defecto='10'):
    valor = request.GET.get(parametro, defecto)

    if valor not in OPCIONES_POR_PAGINA:
        valor = defecto

    return valor, int(valor)


def parametros_sin_pagina(request, parametros):
    query_params = request.GET.copy()

    for parametro in parametros:
        query_params.pop(parametro, None)

    return query_params.urlencode()
