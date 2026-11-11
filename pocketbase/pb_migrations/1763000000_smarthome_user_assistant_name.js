/// <reference path="../pb_data/types.d.ts" />
// Nom donné à l'assistant par la personne (affiché dans la conversation et donné au LLM ; vide = ASSISTANT_NAME).
migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.add(new TextField({ name: "assistant_name", max: 40 }));
  app.save(users);
}, (app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.removeByName("assistant_name");
  app.save(users);
});
