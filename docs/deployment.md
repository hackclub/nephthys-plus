# Deploying Nephthys on Orchard

The easiest way to run Nephthys in production is the **Nephthys Plus** template on [Orchard](https://github.com/hackclub/orchard). The template creates the Postgres database, builds this repository's `Dockerfile`, wires every environment variable, and sets up the domain and HTTPS. You only create the Slack app and fill in a form.

You can also run Nephthys elsewhere (a Docker compose file, another PaaS). Use the [configuration reference](configuration.md) for the environment variables and replace the Orchard steps with your own.

## 1. Creating the Slack app

Do this first. It has to be done by a Workspace Admin, otherwise the bot can't fully delete threads in the tickets channel.

1. Go to <https://api.slack.com/apps>
2. Create New App > From a manifest
3. Select YAML. Paste the [manifest.yml](../manifest.yml) file (but don't submit it yet)
4. Replace the `https://nephthys.hackclub.com/` URLs in the manifest with the domain you'll deploy on (for example `https://help.example.com/`), and update the `name`, `description`, and bot user's `display_name`
5. Review the app's permissions and create it
6. Click **OAuth & Permissions** in the sidebar and install the app to your workspace
7. Copy the **Bot User OAuth Token** (`xoxb-...`) and **User OAuth Token** (`xoxp-...`) from that page, and the **Signing Secret** from **Basic Information**

You'll also need the IDs (`C...`) of the channels the bot uses: the help channel where people ask questions, the behind-the-scenes (BTS) channel for your helpers, and optionally a tickets channel (where a message for every open ticket is posted for helpers; if you don't set one, no ticket messages are posted and helpers work from the question threads) and a heartbeat channel for log messages. Your own Slack user ID (`U...`) is used as the maintainer, who gets pinged when the bot breaks.

## 2. Deploying the template

1. In Orchard, open the **New** page and search for **Nephthys Plus** (or pick it from the bot category)
2. Fill in the parameters:

   | Parameter | What to enter |
   | --------- | ------------- |
   | App Name | Name for the app; the database is named `<app name>-db` |
   | Domain | The domain you used in the Slack manifest, e.g. `help.example.com`. Point its DNS at your Orchard cluster first |
   | Slack Bot Token / User Token / Signing Secret | From step 1 |
   | BTS / Help Channel ID | Channel IDs, `C...` |
   | Ticket Channel ID | Optional. Leave empty to post no ticket messages |
   | Heartbeat Channel ID | Optional log channel |
   | Maintainer User ID | Your Slack ID, `U...` |
   | Program | The name shown in messages. Use a name that is not in `nephthys/transcripts/transcripts/` so your channel IDs and the settings below are used. A built-in name (like the default `help`) uses that program's own hardcoded channels and text instead |
   | FAQ URL | Optional link to your FAQ, used in welcome messages and the FAQ macro |
   | App Title | Shown to helpers at the top of the App Home and in the Lobby |

   Everything else is optional; see [Optional settings](#optional-settings).

3. Deploy. Orchard creates the database, builds the image and deploys it. The first build takes a few minutes

The template gives the app and database 100m CPU and 512 MiB memory each. Adjust them on the deployed resources if your workspace needs more.

## 3. Final prerequisites

1. Invite the bot to the BTS and help channels, and to the tickets and heartbeat channels if you set them. Slack hides channels from a bot that isn't a member, and the bot won't start if it can't post to the heartbeat channel
2. If you use a tickets channel, add the user who installed the Slack app (probably you!) to it
3. Make sure your domain's DNS record exists
4. You can also set a profile picture for the bot in the Slack app settings

## 4. Checking it works

A message should show up in the heartbeat channel, and the bot should respond to messages in the help channel. If it doesn't, check the app's logs in Orchard and make sure the request URLs in the Slack app (**Event Subscriptions** and **Interactivity & Shortcuts**) match your domain and end in `/slack/events`.

## Optional settings

All of these are template parameters, and map to the environment variables in [configuration.md](configuration.md). To change one later, edit the parameter and redeploy (or edit the environment variable on the app).

- **AI API key and base URL**: ticket titles and category tags. Defaults to Hack Club AI. If you use another provider, pick one that doesn't train on your prompts. The AI model parameters and category tagging switch are in the same section
- **Slack App Token** (`xapp-...`, needs `connections:write`): turns on socket mode, so Slack doesn't need a public URL
- **Helper OAuth client ID, client secret and token encryption key**: let helpers connect their Slack accounts so macros can delete their own trigger messages. Set all three and add `https://your-domain/slack/oauth/callback` to the Slack app's redirect URLs. Generate the key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- **HCA client ID and secret**: the Lobby and API keys. Create an OAuth app on [Hack Club Auth](https://auth.hackclub.com/developer/apps/new) with the `slack_id` scope and the redirect URI `https://your-domain/oauth/callback`. Set both or neither. The session secret is generated for you
- **Custom messages**: when Program isn't a built-in name, you can change the bot's messages by adding environment variables to the app, such as `TICKET_CREATE`, `FIRST_TICKET_CREATE`, `TICKET_RESOLVE` or `RESOLVE_TICKET_BUTTON`, plus the FAQ settings (`FAQ_CANVAS_ID` turns on AI linking to the exact FAQ answer). See [Custom program text](configuration.md#custom-program-text) for the full list. Macro replies keep their defaults
- **Prometheus API key**: audited deletion for `?threadrip` and `?deleteop`
- **Ticket feedback, daily summary, credit non-helpers, stale ticket days, log level**: feature switches, see [configuration.md](configuration.md)

## Updating

The template builds from the `main` branch of this repository. Redeploy the app in Orchard to pick up new commits. Database migrations are applied by the app on start.
