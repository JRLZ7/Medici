# Security

Medici is designed for one user's local computer. Keep the default loopback binding. Do not deploy it or expose it over your network without adding authentication, authorization, HTTPS, and a deployment security review.

Private files live outside frontend assets. Generated IDs, size limits, media inspection, bound SQL parameters, strict request origins, and write headers establish the initial local security boundary. Details and limitations are in the README.

Never commit personal or laboratory recordings, databases, API credentials, or exports. Review Git's staged diff before committing. The application currently has no model provider or external upload integration.

If reporting a vulnerability, do not include credentials, sensitive footage, or private experiment records in a public issue. Contact the repository owner privately with a minimal non-sensitive reproduction first. No dedicated security contact or response SLA is established yet.
