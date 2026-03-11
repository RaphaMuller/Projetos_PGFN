import os
from datetime import datetime
from Managers.autenticador import GoogleOAUTH
from Managers.controlador_Planilha import ControladorPlanilha
from Managers.controlador_drive import ControladorDrive
from Managers.gmail_Manager import GmailManager
from Managers.log_manager import Logger
from Utils.secrets import Planilhas
from Utils.secrets import Pastas
from Utils.user import User

NOME_LOGGER_SISTEMA = "Robo E-Processo"
log_filename = f"Logs/LogRoboPDF_{datetime.now().strftime('%d/%m/%Y_%H-%M-%S')}.log"
manager = Logger(log_filename, name=NOME_LOGGER_SISTEMA)
log = manager.get_logger()
log.info("SISTEMA INICIADO!")

# Instâncias principais
auth = GoogleOAUTH()
drive = ControladorDrive(auth)
sheets = ControladorPlanilha(auth)
gmail = GmailManager(auth)

cargos_autorizados = ['Tecnico']

def mainRobo_PDF():

    log.debug('\nINICIANDO TELA DE MONITORAMENTO DO ROBO\n')
    log.info("\nIniciando execução do robô de renomeação e movimentação de PDFs\n")
    controleAdm()
    # Faz a leitura da planilha com os processos a serem renomeados e seus digitalizadores.
    planilha_processos = ControladorPlanilha(
        autenticador=auth,
        planilha_id=Planilhas.RENOMEAR_PROCESSOS,
        planilha_nome='Processos_Para_Renomear'
    )

    dados = planilha_processos.read_to_json()
    log.info(f'Total de processos encontrados: {len(dados)}')

    processos_conferidos = [
        (p['PROCESSOS CONFERIDOS'].strip(),
         p['QUEM DIGITALIZOU?'].strip())
        for p in dados
    ]

    lista_formatada = "\n".join([f"{p[0]}, {p[1]}" for p in processos_conferidos])
    log.info(f'\nProcessos a serem modificados:\n {lista_formatada}\n')
    executar_fluxo_drive(processos_conferidos, drive)

    # Subir log para o Drive após execução
    drive.upload_arquivo(
        pasta_destino_id=Pastas.LOGS_ROBOS,
        caminho_arquivo=log_filename,
        nome_arquivo=os.path.basename(log_filename)
    )

def controleAdm():
    usuario = User(auth)
    if usuario.perfil not in cargos_autorizados:
        raise PermissionError(f'Acesso negado: Cargo {usuario.perfil} não tem permissão para executar essa automação')

    log.info(f'Acesso liberado para {usuario.perfil}, executando robô...')

# Pega os ID's das pastas dos digitalizadores
def get_pasta_id(digitalizador):
    digitalizadores = Pastas.PASTAS_DIGITALIZADORES
    digitalizador_normalizado = digitalizador.strip().lower()

    if digitalizador_normalizado in digitalizadores:
        id_pasta = digitalizadores[digitalizador_normalizado]
        log.info(f"ID da pasta do digitalizador '{digitalizador}' encontrado: {id_pasta}")
        return id_pasta
    else:
        log.warning(f"[AVISO] Digitalizador '{digitalizador}' não encontrado.")
        return None

def limpeza_processos(processos_com_erro):

    log.warning("RESUMO DE ERROS ENCONTRADOS:\n")
    for p in processos_com_erro:
        log.warning(
            f"ID: {p['processo']} | "
            f"Quem: {p['digitalizador']} | "
            f"Motivo: {p['erro']}\n"
        )
    # Prepara os dados de erro
    lista_processos = [item['processo'] for item in processos_com_erro]
    lista_digitalizadores = [item['digitalizador'] for item in processos_com_erro]

    # Configura os IDs antes da chamada
    sheets.set_planilha_id(Planilhas.RENOMEAR_PROCESSOS)
    sheets.set_nome_planilha('Processos_Para_Renomear')

    try:
        # Se a lista de erro está vazia, enviamos um dicionário vazio.
        # O batch_update vai limpar as colunas e sair no 'if not valores_por_coluna'
        dados_update = {}
        if lista_processos:
            dados_update = {
                "PROCESSOS CONFERIDOS": lista_processos,
                "QUEM DIGITALIZOU?": lista_digitalizadores
            }

        log.info("Iniciando limpeza e atualização da planilha de controle...")
        sheets.batch_update(
            nome_colunas=["PROCESSOS CONFERIDOS", "QUEM DIGITALIZOU?"],
            valores_por_coluna=dados_update,
        )
        log.info("Planilha atualizada com sucesso.\n")
        
    except Exception as e:
        log.error(f"[ERRO CRÍTICO] Falha ao limpar planilha: {str(e)}\n")

def executar_fluxo_drive(processos_conferidos, drive: ControladorDrive):
    processos_com_erro = []
    contador = 0
    try:
        # Lista todas as subpastas dentro da pasta EProcesso
        pastas_existentes = drive.listar_arquivos(Pastas.EProcesso)

        # Conta quantas pastas existem com o prefixo "Lote - "
        num_lotes = sum(
            1 for item in pastas_existentes
            if item.get('mimeType') == 'application/vnd.google-apps.folder' and item.get('name', '').startswith('Lote - ')
        )
        # Cria a nova pasta com o próximo número
        pasta_lote = f"Lote - {num_lotes + 1} - {datetime.now().strftime('%d-%m-%Y - %H:%M')}" 
        lote_id = drive.criar_pasta(pasta_lote, pasta_pai_id=Pastas.EProcesso)

        if lote_id:
            log.info(f"Pasta '{pasta_lote}' criada com sucesso! ID: {lote_id}")

    except FileNotFoundError:
        log.error(f'Não foi possivel criar a pasta {pasta_lote}')
        return

    for numero_processo, digitalizador in processos_conferidos:
        try:
            log.info(f"🔄 Iniciando fluxo para processo {numero_processo}\n")
            pasta_digitalizador_id = get_pasta_id(digitalizador)

            # Verifica se o digitalizador tem pasta cadastrada.
            if not pasta_digitalizador_id:
                msg = f'[AVISO] Processo: Nº - {numero_processo} sem ID de pasta de origem'
                log.error(f'\n{msg}\n')
                processos_com_erro.append({
                    'processo': numero_processo,
                    'digitalizador': digitalizador,
                    'erro': msg
                })
                continue

            # Verifica por nome se a pasta(numero_processo) existe dentro da pasta do digitalizador.
            pasta_origem = drive.buscar_pasta_por_nome(numero_processo, pasta_pai_id=pasta_digitalizador_id)
            if not pasta_origem:
                msg = f"[AVISO] Pasta do processo: Nº - {numero_processo} não encontrada."
                log.error(f"{msg}\n")
                processos_com_erro.append({
                    'processo': numero_processo,
                    'digitalizador': digitalizador,
                    'erro': msg
                })
                continue

            
            # Verifica se existe algum arquivo dentro da pasta(numero_processo).
            arquivos = drive.listar_arquivos(pasta_origem['id'])
            if not arquivos:
                msg = f"[AVISO] Nenhum arquivo encontrado na pasta do processo: Nº - {numero_processo}"
                log.warning(f"{msg}\n")
                processos_com_erro.append({
                    'processo': numero_processo,
                    'digitalizador': digitalizador,
                    'erro': msg
                })
                continue

            # Verifica se o .pdf responsavel pelo fluxo está na pasta.
            arquivo_pai = any(
                arq['name'].strip() == f'{numero_processo}.pdf'
                for arq in arquivos
            )
            if not arquivo_pai:
                msg = "[AVISO] O conteudo da pasta não condiz com o numero do processo escrito nela."
                log.warning(f"{msg}\n")
                processos_com_erro.append({
                    'processo': numero_processo,
                    'digitalizador': digitalizador,
                    'erro': msg
                })
                continue

            # Verifica se foi criado a pasta destino para o processo.
            pasta_destino_id = drive.criar_pasta(numero_processo, pasta_pai_id=lote_id)
            if not pasta_destino_id:
                msg = f"[AVISO] Não foi possível criar pasta de destino para o processo: Nº - {numero_processo}"
                log.error(f"{msg}\n")
                processos_com_erro.append({
                    'processo': numero_processo,
                    'digitalizador': digitalizador,
                    'erro': msg
                })
                continue

            # Copia para a pasta destino e renomeia apenas o arquivo com numero do processo.
            for arquivo in arquivos:
                novo_arquivo_id = drive.copiar_arquivo(arquivo['id'], parents=[pasta_destino_id])

                if arquivo['name'].strip() == f'{numero_processo}.pdf':
                    novo_nome = f'P{numero_processo}_V1_A0V0_T07-54-369-664_S00001_Livre.pdf'
                    drive.renomear_arquivo(novo_arquivo_id, novo_nome)

            log.info(f"[OK] Processo {numero_processo} copiado e arquivos renomeados.\n")
            contador += 1

        except Exception as e:
            msg = f"[ERRO] Erro inesperado ao processar o processo {numero_processo}"
            log.error(f"{msg}\nErro: {str(e)}")
            processos_com_erro.append({
                'processo': numero_processo,
                'digitalizador': digitalizador,
                'erro': msg
            })
            continue

    if processos_com_erro:
        limpeza_processos(processos_com_erro)

        corpo_html_com_erros = """
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #d9534f;">Relatório de Erros - Robô E-Processo</h2>
                <p>Os seguintes processos apresentaram falhas e foram devolvidos para a planilha:</p>
                <hr>
        """
        for p in processos_com_erro:
            corpo_html_com_erros += f"""
                <div style="margin-bottom: 15px; border-left: 4px solid #d9534f; padding-left: 10px;">
                    <p style="margin: 0;"><b>Processo:</b> {p['processo']}</p>
                    <p style="margin: 0;"><b>Digitalizador:</b> {p['digitalizador']}</p>
                    <p style="margin: 0; color: #555;"><b>Erro:</b> {p['erro']}</p>
                </div>
            """

        corpo_html_com_erros += """
                <hr>
                <p style="font-size: 12px; color: #888;">Este é um e-mail automático enviado pelo sistema.</p>
                </body>
            </html>
        """
        gmail.enviar_email(
            destinatario='josmila.silva@pgfn.gov.br',
            assunto=f'Alerta: {len(processos_com_erro)} Erros no Robô E-Processo',
            corpo= corpo_html_com_erros,
            is_html=True
        )

    else:
        log.info("\nSUCESSO TOTAL: Nenhum erro na execução do fluxo de transferência")

        corpo_sucesso = f"""
            <html>
                <body style="font-family: Arial, sans-serif; color: #333;">
                    <div style="background-color: #dff0d8; padding: 20px; border-radius: 5px; border: 1px solid #d6e9c6;">
                        <h2 style="color: #3c763d; margin-top: 0;">✅ Processamento Concluído!</h2>
                        <p>Olá,</p>
                        <p>O <b>Robô E-Processo</b> finalizou a execução com sucesso.</p>
                        <p><b>Resumo:</b> Todos os processos foram renomeados e movidos corretamente. Não houve intercorrências.</p>
                    </div>
                    <br>
                    <p style="font-size: 12px; color: #888;">Data/Hora do encerramento: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
                    <p style="font-size: 12px; color: #888;">Este é um aviso automático do sistema.</p>
                </body>
            </html>
            """

        gmail.enviar_email(
            destinatario="josmila.silva@pgfn.gov.br",
            assunto="[SUCESSO] Robô E-Processo - Execução Finalizada",
            corpo=corpo_sucesso,
            is_html=True
        )

    log.info(f"\nTotal de processos finalizados com sucesso: {contador} de {len(processos_conferidos)}")

if __name__ == "__main__":
    mainRobo_PDF()
