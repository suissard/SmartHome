# Comptes utilisateurs (PocketBase)

Facultatif : sans PocketBase (`AUTH_PROVIDER=none`), SmartHome fonctionne comme avant avec le seul jeton `GATEWAY_AUTH_TOKEN`.

PocketBase ne sert qu'à **identifier** les personnes qui utilisent la PWA. La PWA ne lui parle jamais :
la passerelle vérifie l'identifiant et le mot de passe, puis lie la session au compte (son rôle limite les outils
et l'accès aux paramètres, voir `AUTH_ROLE_TOOLS` et `AUTH_ADMIN_ROLES` dans `.env`).
Le micro de l'ordinateur n'identifie pas la voix : il utilise le compte fixe « Foyer » (`AUTH_LOCAL_ROLE`).

## Mise en place

1. Télécharger le binaire PocketBase (>= 0.23) pour votre système depuis https://github.com/pocketbase/pocketbase/releases
   et le placer dans ce dossier (`pocketbase/pocketbase`, ou `pocketbase.exe` sous Windows).
2. Lancer PocketBase **sur cette machine uniquement** (il n'a pas à être joignable depuis le réseau) :

   ```bash
   ./pocketbase/pocketbase serve --http 127.0.0.1:8090 --dir pocketbase/pb_data --migrationsDir pocketbase/pb_migrations
   ```

   La migration ajoute le champ `role` (`admin`, `member`, `guest`) à la collection `users` et ferme l'inscription libre.
3. Créer le compte administrateur PocketBase (lien affiché au premier lancement), puis les comptes du foyer
   dans l'interface `http://127.0.0.1:8090/_/` (collection `users`, champ `role`).
4. Dans `.env` : `AUTH_PROVIDER=pocketbase` (et `POCKETBASE_URL` si besoin), puis redémarrer SmartHome.
5. Vérifier un compte sans démarrer l'assistant : `python core/users.py`.

`GATEWAY_AUTH_TOKEN` reste obligatoire pour un accès depuis le réseau : il reste l'accès administrateur
(appairage par QR code, serveur MCP, `python -m gateway.client`). Sur une passerelle locale sans jeton,
tout client local est administrateur et les comptes ne sont pas demandés.
