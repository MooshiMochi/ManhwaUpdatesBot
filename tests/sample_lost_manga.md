---
export_type: lost_manga
version: 1.1
user:
  id: {{user_id}}
  username: {{user_name}}
generated_at: {{iso_utc_timestamp}}
counts:
  bookmarked_total: {{count_bookmarked_total}}
  subscribed: {{count_subscribed}}
  server_tracked: {{count_server_tracked}}
---

# 🧭 Lost Manga Export

> These entries come from sources that are no longer supported.

## Legend

- **Source**: Original (now-unsupported) site/domain name.
- **Last Read**: Latest chapter the user reached (number and title if available).
- **Last Read URL**: Chapter link, if stored.

---

## 📁 Bookmarked Manga by Folder (Collapsible)

> Click a folder to expand/collapse its bookmarked manga.

{{#each bookmark_folders}}
<details>
<summary><strong>{{folder_name}}</strong> — {{folder_count}} item(s)</summary>

| Title | Source | Last Read | Last Read URL |
|------:|:------:|:---------:|:-------------:|

{{#each items}}
| {{title}} | {{source_domain}} | {{#if last_read.number}}Ch. {{last_read.number}}{{/if}}{{#if last_read.title}} —
{{last_read.title}}{{/if}} | {{last_read.url}} |
{{/each}}

</details>

{{/each}}

> Overall bookmarked total: **{{count_bookmarked_total}}**

---

## 🔔 Subscribed Manga (Lost Sources)

| Title | Source | Last Read | Last Read URL | Subscribed Since |
|------:|:------:|:---------:|:-------------:|:----------------:|

{{#each subscribed}}
| {{title}} | {{source_domain}} | {{#if last_read.number}}Ch. {{last_read.number}}{{/if}}{{#if last_read.title}} —
{{last_read.title}}{{/if}} | {{last_read.url}} | {{dates.subscribed}} |
{{/each}}

> Total: **{{count_subscribed}}**

---

## 🏷️ Server-Tracked Manga (Lost Sources)

> Only includes servers the user is currently in.

{{#each servers}}

### {{server.name}} (ID: {{server.id}})

| Title | Source | Last Read | Last Read URL | Tracked Since | Channel/Scope |
|------:|:------:|:---------:|:-------------:|:-------------:|:-------------:|

{{#each tracked}}
| {{title}} | {{source_domain}} | {{#if last_read.number}}Ch. {{last_read.number}}{{/if}}{{#if last_read.title}} —
{{last_read.title}}{{/if}} | {{last_read.url}} | {{dates.tracked_since}} | {{channel_or_scope}} |
{{/each}}

> Server total: **{{server.count_tracked}}**

{{/each}}

> Overall server-tracked total: **{{count_server_tracked}}**
