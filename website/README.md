# audium website

The landing page: a static site, English at `/`, German at `/de/`. No framework and no
dependencies, only Node 24.

```
website/
  build.mjs         renders the pages into dist/ (git-ignored)
  src/page.mjs      the markup, one function for both languages
  src/i18n/*.mjs    the texts; keep en.mjs and de.mjs in step
  public/           copied as-is: CSS, JS, icons, .htaccess, robots.txt
```

Build and look at it locally:

```bash
node website/build.mjs
npx serve website/dist      # or any static file server
```

`SITE_URL=https://audium.example node website/build.mjs` also writes canonical links,
`sitemap.xml` and a `robots.txt` pointing to it.

The page loads nothing from other servers (no Google Fonts, no analytics) and sets no cookies.
Fonts: put `space-grotesk.woff2`, `inter.woff2` and `jetbrains-mono.woff2` (variable fonts, SIL
OFL) into `public/assets/fonts/`; until then the system fonts are used.

## Deployment

`.github/workflows/website.yml` builds the site on every push to `main` that changes `website/`
and copies it with rsync over SSH to the netcup webspace. Pull requests only build it. A deploy
can also be started by hand: Actions > Website > Run workflow.

### One-time setup

1. **Find the SSH details** in the netcup Webhosting Control Panel (WCP): under SSH access the
   host (e.g. `hosting123456.a2e7f.netcup.net`), the user (`hosting123456`) and the port. Under
   Websites / Domains, the document root of the domain (e.g. `/httpdocs`). Turn on SSL
   (Let's Encrypt) for the domain there as well.

2. **Create a key just for deploys** on your own computer (no passphrase, GitHub has to use it
   unattended):

   ```bash
   ssh-keygen -t ed25519 -N "" -C "github-actions audium website" -f audium-website
   ```

   This makes `audium-website` (private) and `audium-website.pub` (public).

3. **Put the public key on the webspace**, then check that the key login and rsync work:

   ```bash
   ssh-copy-id -i audium-website.pub -p <port> <user>@<host>
   ssh -i audium-website -p <port> <user>@<host> "rsync --version && ls"
   ```

   Without `ssh-copy-id` (Windows): log in with the password and append the content of
   `audium-website.pub` to `~/.ssh/authorized_keys` (folder 700, file 600).

4. **Pin the host key:** `ssh-keyscan -p <port> <host>` prints the lines for
   `WEBSITE_SSH_KNOWN_HOSTS`.

5. **In GitHub**, Settings > Secrets and variables > Actions:

   | Kind | Name | Value |
   |---|---|---|
   | Secret | `WEBSITE_SSH_KEY` | full content of `audium-website` (the private key) |
   | Secret | `WEBSITE_SSH_KNOWN_HOSTS` | output of step 4 |
   | Variable | `WEBSITE_SSH_HOST` | host |
   | Variable | `WEBSITE_SSH_USER` | user |
   | Variable | `WEBSITE_SSH_PORT` | port, only if not 22 |
   | Variable | `WEBSITE_PATH` | document root, e.g. `/httpdocs` |
   | Variable | `WEBSITE_URL` | `https://<your domain>` |

   Then delete the private key file from your computer, or keep it somewhere safe.

6. Run the workflow once by hand (Actions > Website > Run workflow) and open the domain.

**Careful:** the deploy uses `rsync --delete`. Everything in `WEBSITE_PATH` that is not part of
the site is removed (only `.well-known/` is kept). Use a folder that holds the website and nothing
else.
