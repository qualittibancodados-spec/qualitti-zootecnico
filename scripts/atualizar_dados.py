"""
Atualiza os dados do painel Qualitti Zootécnico a partir das planilhas
na pasta do Google Drive.

Como funciona:
1. Conecta na pasta do Drive usando uma conta de serviço (só leitura).
2. Lê TODOS os arquivos .xlsx/.xlsm da pasta e identifica qual é qual
   pela ABA INTERNA (não pelo nome do arquivo, que pode variar):
     - aba 'bd_mort'      -> base de Mortalidade
     - aba 'bd_lotes'     -> base de Resultado Zootécnico (abate)
     - aba 'Bd_Condenas'  -> base de Condenas
3. Roda a mesma lógica de agregação que já usávamos manualmente.
4. Grava os JSONs em /data, prontos para o site consumir via fetch().

Rodado automaticamente pelo GitHub Actions (.github/workflows/atualizar-dados.yml).
"""
import io
import json
import math
import os
import sys
from collections import defaultdict

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
FOLDER_ID = os.environ['GDRIVE_FOLDER_ID']
SERVICE_ACCOUNT_JSON = os.environ['GDRIVE_SERVICE_ACCOUNT_KEY']  # conteúdo do JSON, não o caminho
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if pd.isna(v):
        return None
    return v


def conectar_drive():
    info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def listar_planilhas(servico):
    """Lista todos os .xlsx/.xlsm na pasta (não entra em subpastas)."""
    query = (
        f"'{FOLDER_ID}' in parents and trashed = false and "
        "(mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' "
        "or mimeType = 'application/vnd.ms-excel.sheet.macroEnabled.12' "
        "or name contains '.xlsx' or name contains '.xlsm')"
    )
    resultado = servico.files().list(q=query, fields='files(id, name, modifiedTime)').execute()
    return resultado.get('files', [])


def baixar_arquivo(servico, file_id):
    request = servico.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf


def identificar_planilha(xls_bytes):
    """Abre o Excel e identifica qual base é, pela aba interna."""
    xl = pd.ExcelFile(xls_bytes)
    abas = set(xl.sheet_names)
    if 'bd_mort' in abas:
        return 'mortalidade', xl
    if 'bd_lotes' in abas:
        return 'resultado', xl
    if 'Bd_Condenas' in abas:
        return 'condenas', xl
    return None, xl


# ============================================================
# MORTALIDADE
# ============================================================
def processar_mortalidade(xl):
    df = pd.read_excel(xl, sheet_name='bd_mort')
    df = df.dropna(subset=['Núcleo', 'Aviário']).copy()

    # ---- RAW_DATA (enxuto: abertos + últimos 3 fechados por aviário) ----
    raw_cols = ['Núcleo', 'Aviário', 'Lote', 'Situação', 'Data Aloj', 'Ano', 'Rodada',
                'Alojadas', 'Sexo', 'Idade', 'Morte', 'Elim', 'Total Baixa', 'Peso']
    abertos_lotes = set(df[df['Situação'] == 'Aberto']['Lote'].unique())
    fech = df[df['Situação'] == 'Fechado'][['Lote', 'Aviário', 'Data Aloj']].drop_duplicates()
    fech['Data Aloj'] = pd.to_datetime(fech['Data Aloj'])
    fechados_recentes = set()
    for av, g in fech.groupby('Aviário'):
        fechados_recentes.update(g.sort_values('Data Aloj')['Lote'].tolist()[-3:])
    manter = abertos_lotes | fechados_recentes
    sub = df[df['Lote'].isin(manter)][raw_cols].copy()
    sub['Data Aloj'] = pd.to_datetime(sub['Data Aloj'], errors='coerce').dt.strftime('%Y-%m-%d')
    raw_records = [{k: clean(v) for k, v in r.items()} for r in sub.to_dict('records')]
    salvar('mortalidade_data.json', raw_records)

    # ---- RESUMO_LOTES (1 linha por lote) ----
    resumo = []
    for lote_id, g in df.groupby('Lote'):
        g = g.sort_values('Idade')
        situacao = g['Situação'].iloc[0]
        alojadas = int(g['Alojadas'].iloc[0])
        idade_final = int(g['Idade'].max())
        morte_acum = int(g['Morte'].fillna(0).sum())
        elim_acum = int(g['Elim'].fillna(0).sum())
        total_acum = int(g['Total Baixa'].fillna(0).sum())
        peso_final = g['Peso'].dropna()
        peso_final = float(peso_final[peso_final > 0].iloc[-1]) if (peso_final > 0).any() else None
        gpd = round(peso_final / idade_final, 1) if (peso_final and idade_final > 0) else None
        resumo.append({
            'loteId': str(lote_id), 'lote': str(lote_id),
            'nucleo': g['Núcleo'].iloc[0], 'aviario': g['Aviário'].iloc[0],
            'situacao': situacao, 'dataAloj': pd.to_datetime(g['Data Aloj'].iloc[0]).strftime('%Y-%m-%d'),
            'sexo': g['Sexo'].iloc[0], 'incubatorio': clean(g['Incubatório'].iloc[0]) if 'Incubatório' in g.columns else None,
            'alojadas': alojadas, 'idadeFinal': idade_final,
            'totalBaixaAcum': total_acum, 'morteAcum': morte_acum, 'elimAcum': elim_acum,
            'pctTotal': round(total_acum / alojadas * 100, 3), 'pctNatural': round(morte_acum / alojadas * 100, 3),
            'pctElim': round(elim_acum / alojadas * 100, 3),
            'pesoFinal': peso_final, 'gpdFinal': gpd
        })
    salvar('resumo_lotes.json', resumo)

    # ---- AGG_IDADE (curva por idade, por sexo x situação) ----
    SEXOS = ['Todos', 'Machos', 'Fêmeas', 'Mistos']

    def build_agg_idade(filtro_sexo, situacao):
        sub2 = df[df['Situação'] == situacao]
        if filtro_sexo != 'Todos':
            sub2 = sub2[sub2['Sexo'] == filtro_sexo]
        agg = defaultdict(lambda: [0, 0, 0, 0, 0])
        for lote_id, g in sub2.groupby('Lote'):
            g = g.sort_values('Idade')
            alojadas = g['Alojadas'].iloc[0]
            idade_final_l = int(g['Idade'].max())
            med = g.groupby('Idade').agg(b=('Total Baixa', 'sum'), m=('Morte', 'sum'), e=('Elim', 'sum')).fillna(0)
            accB = accM = accE = 0
            acc = {}
            for idade in sorted(med.index):
                accB += med.loc[idade, 'b']; accM += med.loc[idade, 'm']; accE += med.loc[idade, 'e']
                acc[int(idade)] = (accB, accM, accE)
            ultimo = (0, 0, 0)
            for t in range(0, idade_final_l + 1):
                if t in acc:
                    ultimo = acc[t]
                b, m, e = ultimo
                cell = agg[t]
                cell[0] += b; cell[1] += m; cell[2] += e; cell[3] += alojadas; cell[4] += 1
        linhas = []
        for t in sorted(agg.keys()):
            b, m, e, aloj, n = agg[t]
            if aloj == 0:
                continue
            linhas.append({'idade': t, 'pctTotal': round(b / aloj * 100, 4), 'pctNatural': round(m / aloj * 100, 4),
                            'pctElim': round(e / aloj * 100, 4), 'nLotes': n})
        return linhas

    AGG_IDADE = {sx: {'Aberto': build_agg_idade(sx, 'Aberto'), 'Fechado': build_agg_idade(sx, 'Fechado')} for sx in SEXOS}
    salvar('agg_idade.json', AGG_IDADE)

    # ---- AGG_NUCLEO (curva por núcleo, só fechados) ----
    fechados_df = df[df['Situação'] == 'Fechado']

    def build_por_nucleo(filtro_sexo):
        sub2 = fechados_df if filtro_sexo == 'Todos' else fechados_df[fechados_df['Sexo'] == filtro_sexo]
        agg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
        for (nucleo, lote_id), g in sub2.groupby(['Núcleo', 'Lote']):
            g = g.sort_values('Idade')
            alojadas = g['Alojadas'].iloc[0]
            idade_final_l = int(g['Idade'].max())
            med = g.groupby('Idade').agg(b=('Total Baixa', 'sum'), m=('Morte', 'sum'), e=('Elim', 'sum')).fillna(0)
            accB = accM = accE = 0
            acc = {}
            for idade in sorted(med.index):
                accB += med.loc[idade, 'b']; accM += med.loc[idade, 'm']; accE += med.loc[idade, 'e']
                acc[int(idade)] = (accB, accM, accE)
            ultimo = (0, 0, 0)
            for t in range(0, idade_final_l + 1):
                if t in acc:
                    ultimo = acc[t]
                b, m, e = ultimo
                cell = agg[nucleo][t]
                cell[0] += b; cell[1] += m; cell[2] += e; cell[3] += alojadas; cell[4] += 1
        out = {}
        for nucleo, idades in agg.items():
            linhas = []
            for t in sorted(idades.keys()):
                b, m, e, aloj, n = idades[t]
                if aloj == 0:
                    continue
                linhas.append({'idade': t, 'pctTotal': round(b / aloj * 100, 4), 'pctNatural': round(m / aloj * 100, 4),
                                'pctElim': round(e / aloj * 100, 4), 'nLotes': n})
            out[nucleo] = linhas
        return out

    AGG_NUCLEO = {sx: build_por_nucleo(sx) for sx in SEXOS}
    salvar('agg_nucleo_idade.json', AGG_NUCLEO)

    # ---- MORT_DIARIA (só abertos, formato lista por aviário) ----
    ab = df[df['Situação'] == 'Aberto'].copy()
    lista = []
    for (nuc, av), g in ab.groupby(['Núcleo', 'Aviário']):
        g = g.sort_values('Idade')
        alojadas = int(g['Alojadas'].iloc[0])
        sexo = g['Sexo'].iloc[0]
        data_aloj = pd.to_datetime(g['Data Aloj'].iloc[0]).strftime('%Y-%m-%d')
        dias = {}
        for _, r in g.iterrows():
            idade = int(r['Idade'])
            morte = int(r['Morte']) if pd.notna(r['Morte']) else 0
            elim = int(r['Elim']) if pd.notna(r['Elim']) else 0
            dias[str(idade)] = {'total': morte + elim, 'morte': morte, 'elim': elim}
        lista.append({'nucleo': nuc, 'aviario': av, 'sexo': sexo, 'alojadas': alojadas,
                       'dataAloj': data_aloj, 'dias': dias})
    lista.sort(key=lambda x: (x['nucleo'], x['aviario']))
    salvar('mort_diaria_abertos.json', lista)

    print(f"  Mortalidade: {len(resumo)} lotes ({len(abertos_lotes)} abertos)")


# ============================================================
# RESULTADO ZOOTÉCNICO (abate)
# ============================================================
def processar_resultado(xl):
    df = pd.read_excel(xl, sheet_name='bd_lotes')
    ren = {
        'Lote': 'lote', 'Data Abate': 'dataAbate', 'Ano': 'ano', 'Rodada': 'rodada',
        'Sexo': 'sexo', 'Núcleo': 'nucleo', 'Incubatório': 'incubatorio', 'Aviário': 'aviario',
        'Linhagem': 'linhagem', 'Nutrição': 'nutricao', 'Granjeiro': 'granjeiro', 'Tecnico': 'tecnico',
        'Fator Produção': 'fp', 'GMD': 'gmd', 'CA': 'ca', 'IEP': 'iep', '%MortElim Total': 'mortElim',
        'Idade Abate': 'idadeAbate', 'Aves Alojadas': 'alojadas', 'Aves Abatidas': 'abatidas',
        'PM Abate': 'pmAbate', '%Condenas': 'condenas', '% Uniformidade': 'unif', 'Custo': 'custo',
        'Consumo Ração': 'consumoRacao', 'PM_7': 'pm7', 'PM_14': 'pm14', 'PM_21': 'pm21', 'PM_28': 'pm28',
        'PM_35': 'pm35', 'PM_42': 'pm42', 'Média Prev': 'mediaPrev', 'Média Real': 'mediaReal', 'Dif. Média': 'difMedia'
    }
    cols_existentes = [c for c in ren if c in df.columns]
    sub = df[cols_existentes].rename(columns={k: ren[k] for k in cols_existentes})
    if 'unif' in sub.columns:
        sub['unif'] = sub['unif'].where((sub['unif'] >= 0) & (sub['unif'] <= 100))
    if 'dataAbate' in sub.columns:
        sub['dataAbate'] = pd.to_datetime(sub['dataAbate'], errors='coerce').dt.strftime('%Y-%m-%d')
    round_map = {'fp': 1, 'gmd': 2, 'ca': 3, 'iep': 1, 'mortElim': 2, 'idadeAbate': 0, 'pmAbate': 3, 'condenas': 2,
                 'unif': 1, 'custo': 3, 'consumoRacao': 3, 'pm7': 2, 'pm14': 2, 'pm21': 2, 'pm28': 2, 'pm35': 2,
                 'pm42': 2, 'mediaPrev': 3, 'mediaReal': 3, 'difMedia': 3}
    for c, d in round_map.items():
        if c in sub.columns:
            sub[c] = pd.to_numeric(sub[c], errors='coerce').round(d)
    for c in ['alojadas', 'abatidas', 'ano', 'rodada']:
        if c in sub.columns:
            sub[c] = pd.to_numeric(sub[c], errors='coerce').astype('Int64')
    records = [{k: clean(v) for k, v in r.items()} for r in sub.to_dict('records')]
    salvar('resultado_lotes.json', records)
    print(f"  Resultado: {len(records)} lotes")


# ============================================================
# CONDENAS
# ============================================================
def processar_condenas(xl):
    df = pd.read_excel(xl, sheet_name='Bd_Condenas')
    lotes = []
    for (nuc, num, abate), g in df.groupby(['Núcleo', 'Número', 'Abate']):
        peso_total = float(g['Peso Total Kg'].iloc[0])
        aves_abat = int(g['Aves Abatidas'].iloc[0])
        ano_rodada = g['Ano Rodada'].iloc[0]
        ano_rodada = int(ano_rodada) if pd.notna(ano_rodada) else None
        ano_abate = int(g['Ano Abate'].iloc[0])
        rodada = g['Rodada'].iloc[0]
        rodada = int(rodada) if pd.notna(rodada) else None
        mes = g['Mês Abate'].iloc[0]
        incub = g['Incubatório'].iloc[0]
        tipos = {}
        for item, gi in g.groupby('Item'):
            tipos[item] = [round(float(gi['Peso Condena'].sum()), 2), round(float(gi['Qtd Condena'].sum()), 1)]
        lotes.append({
            'nucleo': nuc, 'aviario': int(num), 'ano': ano_rodada, 'rodada': rodada,
            'anoAbate': ano_abate, 'mes': mes if pd.notna(mes) else None,
            'incubatorio': incub if pd.notna(incub) else None,
            'abate': pd.to_datetime(abate).strftime('%Y-%m-%d'),
            'pesoTotal': round(peso_total, 1), 'avesAbat': aves_abat,
            'pesoCond': round(float(g['Peso Condena'].sum()), 2),
            'qtdCond': round(float(g['Qtd Condena'].sum()), 1),
            'tipos': tipos
        })
    lotes.sort(key=lambda x: (x['nucleo'], x['aviario'], x['abate']))
    salvar('condenas_lotes.json', lotes)
    print(f"  Condenas: {len(lotes)} abates")


def salvar(nome_arquivo, dados):
    os.makedirs(DATA_DIR, exist_ok=True)
    caminho = os.path.join(DATA_DIR, nome_arquivo)
    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, separators=(',', ':'))


def main():
    print("Conectando ao Google Drive...")
    servico = conectar_drive()
    arquivos = listar_planilhas(servico)
    print(f"Encontrados {len(arquivos)} arquivo(s) na pasta.")

    processadores = {
        'mortalidade': processar_mortalidade,
        'resultado': processar_resultado,
        'condenas': processar_condenas,
    }
    encontrados = set()

    for arq in arquivos:
        print(f"Lendo: {arq['name']}")
        try:
            xls_bytes = baixar_arquivo(servico, arq['id'])
            tipo, xl = identificar_planilha(xls_bytes)
            if tipo is None:
                print(f"  Aviso: não reconheci a estrutura de '{arq['name']}' (nenhuma aba esperada encontrada) — pulando.")
                continue
            print(f"  Identificado como: {tipo}")
            processadores[tipo](xl)
            encontrados.add(tipo)
        except Exception as e:
            print(f"  ERRO ao processar '{arq['name']}': {e}")

    faltando = set(processadores.keys()) - encontrados
    if faltando:
        print(f"\nAVISO: não encontrei base(s) de: {', '.join(faltando)}. "
              f"Os dados dessas áreas no site ficam com a última versão válida.")

    print("\nAtualização concluída.")


if __name__ == '__main__':
    sys.exit(main())
