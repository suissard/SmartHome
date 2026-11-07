/// <reference path="../pb_data/types.d.ts" />
// Comptes SmartHome (PocketBase >= 0.23) : champ « role » et inscription fermée.
// Seul l'administrateur PocketBase crée les comptes ; personne ne peut changer son propre rôle.
migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.add(new SelectField({
    name: "role",
    values: ["admin", "member", "guest"],
    maxSelect: 1,
  }));
  users.createRule = null;
  users.updateRule = "id = @request.auth.id && @request.body.role:isset = false";
  app.save(users);
}, (app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.removeByName("role");
  users.createRule = "";
  users.updateRule = "id = @request.auth.id";
  app.save(users);
});
