# Alantech ERP

Custom Frappe/ERPNext app for Alantech Industries India Pvt. Ltd.

Built on ERPNext, Frappe HRMS and India Compliance (**version-16**).

It brands the platform for Alantech: app name and logos on the login page, apps
screen, splash screen and favicon, plus a light brand layer (leaf green + water
blue) on top of Frappe v16's Espresso design system for the desk, login and website.

## Requirements

- Frappe / ERPNext `version-16`
- Python 3.14, Node 24, MariaDB 11.8 (Frappe v16 requirements)

## Install

```bash
bench get-app <repo-url> --branch version-16
bench --site <site> install-app alantech_erp
bench build --app alantech_erp
```

Branding values are (re)applied on every `bench migrate`.

## Theme files

| File | Loaded on | Purpose |
|---|---|---|
| `public/css/alantech_tokens.css` | desk + web | Brand palette mapped onto Frappe v16 tokens, buttons |
| `public/css/alantech_desk.css` | desk (`/desk`) | Sidebar, dock, apps screen, forms, lists, workspaces |
| `public/css/alantech_web.css` | web (`/login`, portal) | Login / password pages, website |

## License

Proprietary
