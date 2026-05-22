"""Templates domain package.

Eagerly imports `app.templates.models` so the `Template` SQLAlchemy
class is registered with `Base.metadata` before
`Base.metadata.create_all()` runs in `app.main` startup. This also
ensures `Server.template = relationship("Template", ...)` in
`app.servers.models` resolves at mapper-configuration time.
"""

from . import models  # noqa: F401
