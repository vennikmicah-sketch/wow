# Gen Bot — Railway Ready (File Restock)

Full account generator with setup panel, stock system, text restock, and **file restock**.

## Commands
| Command         | Who     | What                                              |
|-----------------|---------|---------------------------------------------------|
| `/gensetup`     | Admin   | Setup panel (channel, cooldown, services)         |
| `/genpanel`     | Admin   | Posts the public generate dropdown                |
| `/restock`      | Admin   | Paste accounts as text                            |
| `/restockfile`  | Admin   | Tell bot which service, then upload a .txt file   |
| `/stock`        | Everyone| Shows current stock                               |
| `/ping`         | Everyone| Latency                                           |

## File Restock Flow
1. `/restockfile` → type service name
2. Bot says “now upload a .txt”
3. Upload any `.txt` (one account per line)
4. Bot adds them all and confirms new stock

## Deploy
1. Push this folder
2. Set `DISCORD_TOKEN`
3. Enable Server Members Intent + Message Content Intent
4. Invite with `bot` + `applications.commands`
5. Deploy
