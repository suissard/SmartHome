/// <reference path="../pb_data/types.d.ts" />
// Consignes personnelles d'un compte (ton, longueur des réponses...), modifiables par la personne depuis la PWA.
migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.add(new TextField({ name: "instructions", max: 1000 }));
  app.save(users);
}, (app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.removeByName("instructions");
  app.save(users);
});
