/// <reference path="../pb_data/types.d.ts" />
// Voix de synthèse choisie par la personne (identifiant d'une voix Piper de voices/ ; vide = voix par défaut).
migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.add(new TextField({ name: "voice", max: 100 }));
  app.save(users);
}, (app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.removeByName("voice");
  app.save(users);
});
