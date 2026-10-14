import streamlit as st
import pandas as pd
import os
import glob
import re
import plotly.express as px

# Configuração da Página da Aplicação
st.set_page_config(page_title="Dashboard Analítico SINAPSE - Casa dos Ventos", layout="wide")

# Mapeamento de meses para exibição e ordenação amigável
MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

# ==========================================
# 1. MOTOR DE DADOS RECURSIVO COM LIMPEZA (ETL)
# ==========================================
@st.cache_data
def carregar_dados_anual(pasta_raiz):
    arquivos_csv = glob.glob(os.path.join(pasta_raiz, "**", "*.csv"), recursive=True)
    if not arquivos_csv:
        return pd.DataFrame()
        
    lista_df = []
    for arquivo in arquivos_csv:
        try:
            df = pd.read_csv(arquivo, sep=';', encoding='utf-8-sig') 
            df.columns = df.columns.str.strip()
            
            # Remove duplicidades de histórico mantendo apenas o registro original do evento
            df_unico = df.drop_duplicates(subset=['Código'], keep='first').copy()
            
            # Extração de Inteligência
            df_unico['Complexo'] = df_unico['Mensagem'].str.split(r' \| ').str[0].str.replace('Conj. ', '')
            df_unico['Fonte'] = df_unico['Mensagem'].apply(lambda x: 'Fotovoltaica' if isinstance(x, str) and 'Fotovoltaica' in x else ('Eólica' if isinstance(x, str) and 'Eólica' in x else 'N/D'))
            df_unico['Tipo_Ordem'] = df_unico['Mensagem'].apply(lambda x: 'Liberação Total' if isinstance(x, str) and 'Liberação Total' in x else ('Restrição' if isinstance(x, str) and 'Limitar em' in x else 'Outro'))
            
            def extrair_mw(msg):
                if not isinstance(msg, str): return None
                match = re.search(r'Limitar em (\d+)\s*MW', msg, re.IGNORECASE)
                return float(match.group(1)) if match else None
            df_unico['MW_Limite'] = df_unico['Mensagem'].apply(extrair_mw)
            
            # --- NOVO: TRATAMENTO E LIMPEZA DA INFORMAÇÃO ADICIONAL ---
            def extrair_causa_sistemica(info):
                if not isinstance(info, str) or pd.isna(info): 
                    return "Não Informado / Geral"
                # Limpa quebras de linha e o prefixo do ONS
                texto = info.replace('\n', ' ').replace('\r', '').strip()
                texto = re.sub(r'Controle da Inequação:\s*', '', texto, flags=re.IGNORECASE)
                # Tenta pegar apenas o que está dentro dos colchetes [...] que é onde fica a LT/Subestação
                match_colchetes = re.search(r'\[(.*?)\]', texto)
                if match_colchetes:
                    texto = match_colchetes.group(1)
                # Trunca se o texto for absurdamente gigante para não quebrar o gráfico
                if len(texto) > 70:
                    return texto[:67] + "..."
                return texto.strip()
                
            df_unico['Causa_Detalhada'] = df_unico['Informação Adicional'].apply(extrair_causa_sistemica)
            
            # Tratamento de Datas
            df_unico['Data_Hora'] = pd.to_datetime(df_unico['Hora de Cadastro'], dayfirst=True, errors='coerce')
            df_unico['Data'] = df_unico['Data_Hora'].dt.date
            
            lista_df.append(df_unico)
        except:
            continue
            
    if not lista_df: return pd.DataFrame()
    
    df_final = pd.concat(lista_df, ignore_index=True)
    df_final['Num_Mes'] = df_final['Data_Hora'].dt.month
    df_final['Mês'] = df_final['Num_Mes'].map(MESES_PT)
    
    return df_final

# ==========================================
# 2. INTERFACE VISUAL DA APLICAÇÃO
# ==========================================
st.title("⚡ Constrained-off Anual - ONS SINAPSE")
st.markdown("Análise histórica consolidada de restrições de geração (Ano Todo).")

PASTA_ANO = r"G:\Drives compartilhados\O&M\1. COG\3. Pós-operação\22. Relatório Diario SINAPSE\2026"

st.sidebar.header("Controles")
if st.sidebar.button("🔄 Recarregar Ano Todo"):
    st.cache_data.clear()
    st.sidebar.success("Base anual atualizada!")

df_anual = carregar_dados_anual(PASTA_ANO)

if df_anual.empty:
    st.warning(f"Nenhum arquivo encontrado na pasta raiz: {PASTA_ANO}.")
else:
    df_filtrado = df_anual.copy()

    st.sidebar.subheader("Filtros Dinâmicos")
    
    # Filtro 1: Mês
    meses_disponiveis = sorted(df_anual['Num_Mes'].dropna().unique())
    nomes_meses_disponiveis = [MESES_PT[m] for m in meses_disponiveis]
    mes_filtro = st.sidebar.multiselect("1. Filtrar por Mês", options=nomes_meses_disponiveis)
    if mes_filtro:
        df_filtrado = df_filtrado[df_filtrado['Mês'].isin(mes_filtro)]
        
    # Filtro 2: Complexo
    complexos_disponiveis = sorted(df_filtrado['Complexo'].dropna().unique())
    complexo_filtro = st.sidebar.multiselect("2. Filtrar por Complexo", options=complexos_disponiveis)
    if complexo_filtro:
        df_filtrado = df_filtrado[df_filtrado['Complexo'].isin(complexo_filtro)]

    # Filtro 3: Período de Dias
    min_date = df_filtrado['Data'].min()
    max_date = df_filtrado['Data'].max()
    if pd.notnull(min_date) and pd.notnull(max_date):
        data_filtro = st.sidebar.date_input("3. Filtrar Período de Dias", value=(min_date, max_date), min_value=df_anual['Data'].min(), max_value=df_anual['Data'].max())
        if isinstance(data_filtro, tuple) and len(data_filtro) == 2:
            df_filtrado = df_filtrado[(df_filtrado['Data'] >= data_filtro[0]) & (df_filtrado['Data'] <= data_filtro[1])]

    # --- KPIs Dinâmicos ---
    col1, col2, col3 = st.columns(3)
    total_eventos = len(df_filtrado)
    total_restricoes = len(df_filtrado[df_filtrado['Tipo_Ordem'] == 'Restrição'])
    
    # Filtra os "Não Informados" para achar a verdadeira maior causa detalhada
    df_causas_reais = df_filtrado[df_filtrado['Causa_Detalhada'] != "Não Informado / Geral"]
    if not df_causas_reais['Causa_Detalhada'].empty:
        causa_principal = df_causas_reais['Causa_Detalhada'].mode()[0]
    else:
        causa_principal = df_filtrado['Motivo'].mode()[0] if not df_filtrado['Motivo'].empty else "N/D"

    col1.metric("Movimentações no Período (Total)", total_eventos, help="Soma de ordens de corte + ordens de liberação total")
    col2.metric("Ordens de Restrição (Cortes)", total_restricoes, help="Apenas ordens ativas contendo comando de limitação em MW")
    col3.metric("Maior Restrição de Infraestrutura", causa_principal)

    st.markdown("---")

    # --- LINHA 1 DE GRÁFICOS ---
    col_grafico1, col_grafico2 = st.columns(2)

    with col_grafico1:
        st.subheader("Causas Macro (Motivo ONS)")
        if not df_filtrado['Motivo'].dropna().empty:
            contagem_motivos = df_filtrado['Motivo'].value_counts().reset_index()
            contagem_motivos.columns = ['Motivo', 'Quantidade']
            fig_motivo = px.pie(contagem_motivos, values='Quantidade', names='Motivo', hole=0.4)
            st.plotly_chart(fig_motivo, use_container_width=True)
        else:
            st.info("Sem dados suficientes.")

    with col_grafico2:
        st.subheader("Volume de Ordens por Complexo")
        if not df_filtrado['Complexo'].dropna().empty:
            contagem_complexo = df_filtrado['Complexo'].value_counts().reset_index()
            contagem_complexo.columns = ['Complexo', 'Quantidade']
            fig_complexo = px.bar(contagem_complexo, x='Complexo', y='Quantidade', color='Complexo', text_auto=True)
            st.plotly_chart(fig_complexo, use_container_width=True)
        else:
            st.info("Sem dados suficientes.")

    st.markdown("---")
    
    # --- LINHA 2 DE GRÁFICOS (A NOVA MELHORIA) ---
    col_grafico3, col_grafico4 = st.columns(2)
    
    with col_grafico3:
        st.subheader("⚠️ Maiores Restrições Sistêmicas (Subestações / LTs)")
        # Filtra os vazios para o gráfico de causas ser cirúrgico
        df_causas_grafico = df_filtrado[df_filtrado['Causa_Detalhada'] != "Não Informado / Geral"]
        if not df_causas_grafico['Causa_Detalhada'].empty:
            contagem_detalhada = df_causas_grafico['Causa_Detalhada'].value_counts().head(10).reset_index()
            contagem_detalhada.columns = ['Restrição Sistêmica', 'Ocorrências']
            # Gráfico de barras horizontal para facilitar a leitura de nomes longos de LTs
            fig_detalhada = px.bar(contagem_detalhada, y='Restrição Sistêmica', x='Ocorrências', 
                                   orientation='h', color='Ocorrências', text_auto=True)
            fig_detalhada.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_detalhada, use_container_width=True)
        else:
            st.info("Nenhuma informação adicional detalhada encontrada no período filtrado.")
            
    with col_grafico4:
        st.subheader("Evolução Temporal de Restrições (Curva de Tendência)")
        if not df_filtrado['Data'].dropna().empty:
            eventos_por_dia = df_filtrado.groupby('Data').size().reset_index(name='Quantidade')
            eventos_por_dia = eventos_por_dia.sort_values(by='Data')
            fig_tempo = px.line(eventos_por_dia, x='Data', y='Quantidade', markers=True)
            st.plotly_chart(fig_tempo, use_container_width=True)
        else:
            st.info("Sem dados cronológicos.")

    # --- TABELA DE DADOS BRUTOS ---
    with st.expander("Ver Registros Detalhados Filtrados"):
        colunas_exibir = ['Data_Hora', 'Mês', 'Complexo', 'Fonte', 'Tipo_Ordem', 'MW_Limite', 'Motivo', 'Causa_Detalhada', 'Mensagem']
        colunas_existentes = [c for c in colunas_exibir if c in df_filtrado.columns]
        st.dataframe(df_filtrado[colunas_existentes].sort_values(by='Data_Hora', ascending=False), use_container_width=True)