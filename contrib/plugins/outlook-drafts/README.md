# outlook-drafts — approvazione delle bozze Outlook da Telegram

Ogni **nuova bozza** nella cartella Bozze della casella Outlook configurata, chiunque l'abbia creata (Alfred,
Luca, un altro flusso), arriva su Telegram come anteprima con tre pulsanti:

| Pulsante | Cosa fa |
|---|---|
| ✅ **Invia** | invia la bozza **esattamente nella versione mostrata nell'anteprima** |
| ✏️ **Modifica in Outlook** | apre la bozza in Outlook (web o app). In alternativa basta **rispondere al messaggio** su Telegram dicendo cosa cambiare: Alfred aggiorna la bozza e l'anteprima |
| 🗑 **Scarta** | elimina la bozza (finisce in *Posta eliminata*, quindi è recuperabile) |

Le mail che Alfred invia in autonomia, come i follow-up dei cron, **non passano dalle Bozze e non vengono toccate**.

## Come funziona

- Un job cron `no_agent` (senza modello, nessun costo di token) esegue `poll` ogni minuto:
  - legge le Bozze via Microsoft Graph;
  - manda l'anteprima delle bozze nuove;
  - aggiorna l'anteprima se la bozza viene modificata;
  - chiude l'anteprima se la bozza viene inviata o eliminata direttamente da Outlook.
- Una bozza viene annunciata solo quando smette di cambiare da `settle_seconds` (predefinito 120 s). Outlook
  salva in automatico mentre si scrive, quindi senza questa attesa arriverebbero anteprime a metà.
- Al primo avvio le bozze già presenti **non** vengono annunciate (`announce_existing: false`).
- I pulsanti ✅/🗑 usano i pulsanti `gt:send` / `gt:archive` già presenti nell'adattatore Telegram. Quando
  qualcuno li preme, il bot verifica che sia un utente autorizzato ed esegue
  `scripts/gmail-triage/send-draft.sh` / `archive.sh`, che questo plugin installa. Il core non viene modificato.
- **Garanzia:** se la bozza è cambiata dopo l'anteprima, ✅ Invia **non** la invia. Aggiorna l'anteprima e
  chiede di premere di nuovo. Un errore di rete ambiguo durante l'invio non viene mai ritentato alla cieca,
  per non mandare la stessa mail due volte.
- Il tool `outlook_draft` (azioni `list`/`read`/`update`) permette ad Alfred di modificare una bozza in attesa,
  ma **non può inviarla**: la invia solo il pulsante.

## Installazione (profilo di Alfred di Chimera)

1. **Microsoft Entra ID**: sull'app registrata, aggiungere i permessi *Application* `Mail.ReadWrite` e
   `Mail.Send`, con il consenso dell'amministratore.
2. **Limitare l'app alla sola casella di Luca** (obbligatorio). Senza questo l'app può leggere e inviare per
   qualsiasi casella del tenant. Con Exchange Online PowerShell:
   ```powershell
   New-DistributionGroup -Name "Alfred-Mailbox-Scope" -Type Security -Members luca@chimera.example
   New-ApplicationAccessPolicy -AppId <CLIENT_ID> -PolicyScopeGroupId Alfred-Mailbox-Scope `
     -AccessRight RestrictAccess -Description "Alfred: solo casella di Luca"
   Test-ApplicationAccessPolicy -Identity luca@chimera.example -AppId <CLIENT_ID>
   ```
   In alternativa si può usare RBAC for Applications.
3. **Segreti** in `.env`: `MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET`,
   `TELEGRAM_BOT_TOKEN`. Se la pipeline Teams è già configurata, probabilmente ci sono già.
4. **Configurazione** in `config.yaml`:
   ```yaml
   outlook_drafts:
     mailbox: luca@chimera.example     # casella da controllare
     telegram_chat_id: "123456789"     # chat privata di Luca col bot (= suo user id)
     # telegram_thread_id: "42"        # opzionale: topic di un gruppo forum
     settle_seconds: 120
     max_body_chars: 1500
     announce_existing: false
   ```
5. **Chi può premere i pulsanti**: qualunque utente autorizzato del bot. Perché approvi solo Luca, la lista
   degli utenti Telegram autorizzati deve contenere solo il suo ID.
6. **Installare e avviare**:
   ```bash
   cp -r contrib/plugins/outlook-drafts <HERMES_HOME>/plugins/
   plushuman plugins enable outlook-drafts
   plushuman outlook-drafts install          # scrive i 3 script; non sovrascrive script altrui senza --force
   plushuman cron create 'every 1m' --name outlook-drafts --script outlook-drafts-poll.sh --no-agent --deliver telegram
   plushuman gateway restart
   ```
   `install` registra nei file generati il percorso del Python e della home attuali: va rieseguito se
   l'installazione di Alfred si sposta.

## Diagnostica

- `plushuman outlook-drafts status`: bozze tracciate, per stato.
- `plushuman outlook-drafts poll`: esegue un controllo subito.
- Stato in `<HERMES_HOME>/outlook_drafts/state.json`.
- Se Graph o Telegram non rispondono, il job avvisa **una volta** all'inizio del problema, poi una volta all'ora,
  e segnala quando torna a funzionare.

## Limiti noti

- Dopo ✅ il messaggio mostra "✓ bozza inviata da Luca". Dopo 🗑 il testo dell'adattatore dice "✓ archiviato",
  perché il pulsante riusa il verbo `archive`.
- Scegliere ✅ o 🗑 resta un controllo di processo, non una barriera di sicurezza: i cron devono poter inviare in
  autonomia, quindi Alfred mantiene la possibilità tecnica di inviare mail per altre vie.
- I pulsanti dipendono dai nomi fissi `gt:send` / `gt:archive` e dagli script `gmail-triage/`
  dell'adattatore Telegram. Se un aggiornamento li cambia, i test in `contrib/plugins/tests/` lo segnalano.
