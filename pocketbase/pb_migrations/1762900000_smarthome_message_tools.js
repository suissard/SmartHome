/// <reference path="../pb_data/types.d.ts" />
// Outils utilisés lors de chaque échange (nom, arguments, résultat) pour affichage sous forme de pastilles.
migrate((app) => {
  const messages = app.findCollectionByNameOrId("messages");
  messages.fields.add(new JSONField({ name: "tools" }));
  app.save(messages);
}, (app) => {
  const messages = app.findCollectionByNameOrId("messages");
  messages.fields.removeByName("tools");
  app.save(messages);
});
