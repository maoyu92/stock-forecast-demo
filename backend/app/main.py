"""A股 TimesFM 多因子预测 —— FastAPI 后端入口"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .routers import backtest, data, factors, history, portfolio, predict, quotes, screener, stocks, system, watch

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="A股多因子智能预测 API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 局域网演示用途
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(stocks.router)
app.include_router(factors.router)
app.include_router(predict.router)
app.include_router(history.router)
app.include_router(screener.router)
app.include_router(data.router)
app.include_router(watch.router)
app.include_router(quotes.router)
app.include_router(backtest.router)
app.include_router(portfolio.router)


@app.get("/")
def root():
    return {"service": "stock-forecast-api", "docs": "/docs"}
