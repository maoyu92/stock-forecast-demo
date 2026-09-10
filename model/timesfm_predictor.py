"""TimesFM 3.0 多因子预测封装"""
import numpy as np
import pandas as pd
from typing import Optional, List, Tuple, Dict
from timesfm import TimesFM3Forecaster, ForecastConfig


class TimesFMMultiPredictor:
    def __init__(self, max_context: int = 2048, max_horizon: int = 64):
        self.model: Optional[TimesFM3Forecaster] = None
        self.cfg = ForecastConfig(
            max_context=max_context,
            max_horizon=max_horizon,
            normalize_inputs=True,
            use_continuous_quantile_head=True,
            fix_quantile_crossing=True,
            return_backcast=False,
            force_flip_invariance=True,
            infer_is_positive=True,
        )
        self.loaded = False
        self.device = 'cpu'

    def load_model(self):
        if self.loaded:
            return
        self.model = TimesFM3Forecaster.from_pretrained('google/timesfm-3.0-pytorch')
        self.loaded = True

    def _prepare_inputs(self, multi_df: pd.DataFrame, target_col: str, context_len: int) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        cols = [c for c in multi_df.columns if c != target_col]
        ordered = [target_col] + cols
        arr = multi_df[ordered].tail(context_len).values.astype(np.float32)
        context = arr[:, 0]
        if arr.shape[1] > 1:
            past_only = arr[:, 1:]
        else:
            past_only = None
        return context, past_only, None

    def predict(
        self,
        multi_df: pd.DataFrame,
        target_col: str = '',
        horizon: int = 7,
        context_len: int = 180,
        return_quantiles: bool = True,
    ) -> Dict:
        if not self.loaded:
            self.load_model()
        target_col = target_col or str(multi_df.columns[0])
        ctx, past_only, _ = self._prepare_inputs(multi_df, target_col, context_len)
        out = self.model.predict(
            context=ctx,
            horizon=horizon,
            past_only_covariates=past_only,
            return_quantiles=return_quantiles,
            make_positive=True,
            sort_quantiles=True,
            use_znorm=False,
            padding_mode='none',
        )
        forecast = out.forecast
        quantiles = out.quantiles if return_quantiles and out.quantiles is not None else None
        return {
            'forecast': forecast,
            'quantiles': quantiles,
            'horizon': horizon,
            'last_value': float(ctx[-1]),
            'forecast_mean': float(np.mean(forecast)),
            'forecast_min': float(np.min(forecast)),
            'forecast_max': float(np.max(forecast)),
            'forecast_std': float(np.std(forecast)),
            'device': 'cpu',
            'target_col': target_col,
            'factor_columns': [c for c in multi_df.columns if c != target_col],
        }

    def summary(self) -> str:
        return 'TimesFM-3.0-0.3B'


_predictor = None


def get_predictor() -> TimesFMMultiPredictor:
    global _predictor
    if _predictor is None:
        _predictor = TimesFMMultiPredictor()
    return _predictor


if __name__ == '__main__':
    import pandas as pd
    p = get_predictor()
    p.load_model()
    df = pd.DataFrame({
        '中国太保': np.cumsum(np.random.randn(120)) + 30,
        '保险ETF': np.cumsum(np.random.randn(120)) + 1.2,
        '沪深300ETF': np.cumsum(np.random.randn(120)) + 4.1,
        '纳斯达克ETF': np.cumsum(np.random.randn(120)) + 2.3,
    })
    res = p.predict(df, target_col='中国太保', horizon=7, context_len=90)
    print(res)
