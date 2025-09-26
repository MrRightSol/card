from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from .routers.health import router as health_router
from .routers.synth import router as synth_router
from .routers.policy import router as policy_router
from .routers.train import router as train_router
from .routers.score import router as score_router
from .routers.logs import router as logs_router
from .routers.dbadmin import router as dbadmin_router


def create_app() -> FastAPI:
    app = FastAPI(title="Expense Fraud & Policy Compliance API", version="0.1.0")
    # CORS for local Angular dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(synth_router)
    app.include_router(policy_router)
    from .routers.bots import router as bots_router
    app.include_router(bots_router)
    from .routers.policy_chat import router as policy_chat_router
    app.include_router(policy_chat_router)
    app.include_router(train_router)
    from .routers.predict import router as predict_router
    app.include_router(predict_router)
    app.include_router(score_router)
    app.include_router(logs_router)
    app.include_router(dbadmin_router)
    from .routers.clawback import router as clawback_router
    app.include_router(clawback_router)
    # On first run, if the probed capabilities file does not exist, schedule a background probe
    try:
        from .services.model_probe import load_persisted, schedule_probe_background
        if load_persisted() is None:
            schedule_probe_background()
    except Exception:
        # Do not block app startup for probe failures
        pass
    return app


app = create_app()
