/// <reference path="../pb_data/types.d.ts" />
// Historique des conversations de la PWA : chaque compte lit, écrit et efface seulement ses propres messages.
// (L'administrateur de PocketBase, interface /_/, voit tout : projet local, historique conservé sans limite.)
migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  const messages = new Collection({
    type: "base",
    name: "messages",
    listRule: "user = @request.auth.id",
    viewRule: "user = @request.auth.id",
    createRule: "@request.auth.id != '' && @request.body.user = @request.auth.id",
    updateRule: "user = @request.auth.id && @request.body.user:isset = false",
    deleteRule: "user = @request.auth.id",
    fields: [
      { name: "user", type: "relation", required: true, collectionId: users.id, maxSelect: 1, cascadeDelete: true },
      { name: "conversation", type: "text", required: true, max: 64 },
      { name: "turn", type: "text", max: 64 },
      { name: "role", type: "select", required: true, values: ["user", "assistant"], maxSelect: 1 },
      { name: "content", type: "text", max: 100000 },
      // Ordre des messages (deux messages peuvent être créés dans la même milliseconde)
      { name: "seq", type: "number", onlyInt: true },
      { name: "created", type: "autodate", onCreate: true, onUpdate: false },
    ],
    indexes: ["CREATE INDEX idx_messages_user_conversation ON messages (user, conversation, seq)"],
  });
  app.save(messages);
}, (app) => {
  app.delete(app.findCollectionByNameOrId("messages"));
});
