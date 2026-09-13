"""通达信风格选股公式目录 —— 100+ 内置选股策略

每个策略 = {id, 名称, 分类, 描述, 出处, 通达信公式, 参数, 命中详情模板, 强度公式(可选)}
公式用 engine.py 的通达信语法子集书写，最后一条输出线（XG:）即选股信号。
详情模板只允许引用公式中 `:=`/`:` 定义的变量名。

分类：均线形态 / MACD动能 / 摆动指标 / BOLL轨道 / 量价关系 / K线形态 /
     缠论结构(简化) / 趋势突破 / 多条件共振 / 游资打法 / 资金监控(近似) / 风险提示

其中「金三角托」「金蜘蛛」「低位/高位揉搓线」整理自用户提供的材料截图；
「游资进场」「双阴等阳」「BOLL强势回踩中轨」「机构拉升·资金监控」为用户提供的通达信公式移植。
"""
import logging

from ..base import ParamDef, StrategyDef, register
from . import engine

log = logging.getLogger("screener.catalog")

# ============================ 公共片段 ============================

_MA5_20 = "M5:=MA(C,5); M10:=MA(C,10); M20:=MA(C,20);"
_MA = _MA5_20 + " M60:=MA(C,60);"
_MACD = "DIF:=EMA(C,12)-EMA(C,26); DEA:=EMA(DIF,9); MC:=DIF-DEA;"
_KDJ = ("RSV:=(C-LLV(L,9))/(HHV(H,9)-LLV(L,9)+0.0001)*100; "
        "K:=SMA(RSV,3,1); D:=SMA(K,3,1); J:=3*K-2*D;")
_RSI = ("LC:=REF(C,1); "
        "RSI6:=SMA(MAX(C-LC,0),6,1)/SMA(ABS(C-LC),6,1)*100; "
        "RSI12:=SMA(MAX(C-LC,0),12,1)/SMA(ABS(C-LC),12,1)*100;")
_BOLL = "MID:=MA(C,20); UPR:=MID+2*STD(C,20); LOWR:=MID-2*STD(C,20);"
_WR = "WR10:=(HHV(H,10)-C)/(HHV(H,10)-LLV(L,10)+0.0001)*100;"
_CCI = "TYP:=(H+L+C)/3; CCI:=(TYP-MA(TYP,14))/(0.015*AVEDEV(TYP,14)+0.0001);"
_PSY = "PSY:=COUNT(C>REF(C,1),12)/12*100;"
_OBV = "OBV:=SUM(IF(C>REF(C,1),V,IF(C<REF(C,1),-V,0)),0);"
_VR = "VR:=SUM(IF(C>REF(C,1),V,0),26)/(SUM(IF(C<REF(C,1),V,0),26)+0.0001)*100;"
_ZT = "ZT:=C/REF(C,1)>1.097 AND C>=H;"      # 涨停近似：涨幅≥9.7% 且收于最高价
_KBAR = ("BT:=ABS(C-O); RG:=H-L+0.0001; REAL:=BT/RG; "
         "UPSP:=(H-MAX(O,C))/RG; LOSP:=(MIN(O,C)-L)/RG;")   # 实体/上下影占比
_POS = "POS:=(C-LLV(C,60))/(HHV(C,60)-LLV(C,60)+0.0001);"   # 60日区间位置 0~1

# ============================ 策略清单 ============================

S: list[dict] = []


def _s(sid, name, cat, desc, src, formula, detail="", strength="", params=None):
    S.append(dict(id=sid, name=name, cat=cat, desc=desc, src=src, formula=formula,
                  detail=detail, strength=strength, params=params or []))


# ---------- 一、均线形态 ----------

CAT_MA = "均线形态"


def _gold(sid, n1, n2, desc):
    """参数化均线金叉族"""
    _s(sid, f"均线金叉·{n1}上穿{n2}", CAT_MA, desc, "通达信经典均线选股",
       "M1:=MA(C,N1); M2:=MA(C,N2); XG:CROSS(M1,M2);",
       detail="短期线={M1:.2f} 上穿 长期线={M2:.2f}",
       strength="(M1-M2)/M2*100",
       params=[ParamDef("n1", "短期均线", "number", n1, 2, 120, 1, "日", "金叉短期线周期"),
               ParamDef("n2", "长期均线", "number", n2, 3, 250, 1, "日", "金叉长期线周期，需大于短期")])


_gold("ma_gold_5_10", 5, 10, "5日均线上穿10日线，最经典的短线金叉买入信号。")
_gold("ma_gold_5_20", 5, 20, "5日均线上穿20日线，短线转强确认。")
_gold("ma_gold_10_20", 10, 20, "10日均线上穿20日线，波段启动信号。")
_gold("ma_gold_5_30", 5, 30, "5日均线上穿30日线，短线资金进攻中期成本线。")
_gold("ma_gold_20_60", 20, 60, "20日均线上穿60日线，中期趋势由弱转强。")
_gold("ma_gold_20_120", 20, 120, "20日均线上穿半年线，中期趋势确立的标志。")

_s("ma_bull", "均线多头排列", CAT_MA,
   "5/10/20/60日均线自上而下依次多头排列，且收盘价站上5日线——典型强势趋势形态。",
   "通达信经典形态", _MA +
   "XG:M5>M10 AND M10>M20 AND M20>M60 AND C>M5;",
   detail="MA5={M5:.2f} MA10={M10:.2f} MA20={M20:.2f} MA60={M60:.2f}",
   strength="(C-M5)/M5*100")

_s("ma_bull_new", "多头排列·初成", CAT_MA,
   "今日刚刚形成 5>10>20>60 多头排列（昨日尚不满足），捕捉趋势启动第一天。",
   "通达信经典形态", _MA +
   "BULL:=M5>M10 AND M10>M20 AND M20>M60; XG:BULL AND NOT(REF(BULL,1));",
   detail="MA5={M5:.2f} MA20={M20:.2f} MA60={M60:.2f}")

_s("ma120_cross", "站上半年线", CAT_MA,
   "收盘价上穿120日均线且半年线已走平上行，收复中期成本线。",
   "通达信经典形态",
   "M120:=MA(C,120); XG:CROSS(C,M120) AND M120>=REF(M120,10);",
   detail="MA120={M120:.2f}")

_s("ma200_granville", "格兰维尔买点一·上穿年线", CAT_MA,
   "格兰维尔八大法则买点一：价格自下而上穿越200日均线，且长期均线已走平上行。",
   "Granville 八大法则",
   "M200:=MA(C,200); XG:CROSS(C,M200) AND M200>=REF(M200,20);",
   detail="MA200={M200:.2f}")

_s("ma200_pullback", "格兰维尔买点二·回踩年线", CAT_MA,
   "格兰维尔八大法则买点二：上升趋势中年线之上回踩不破（盘中触及年线附近收回）。",
   "Granville 八大法则",
   "M200:=MA(C,200); XG:M200>=REF(M200,10) AND L<=M200*1.02 AND C>M200 AND C>REF(C,1);",
   detail="MA200={M200:.2f} 收盘={C:.2f}")

_s("jusanjiao", "均线金三角托", CAT_MA,
   "先5上穿10、再5上穿20、最后10上穿20，三线依次金叉形成封闭三角形。"
   "最好出现在多头趋势回调到位后的再启动拐点，本公式额外要求20日线已拐头向上。",
   "用户材料《均线汇聚交叉：金三角、金蜘蛛》",
   _MA + ("B1:=BARSLAST(CROSS(M5,M10)); B2:=BARSLAST(CROSS(M5,M20)); "
          "B3:=BARSLAST(CROSS(M10,M20)); "
          "XG:B3<=2 AND B3<B2 AND B2<B1 AND B1<=20 AND M5>M10 AND M10>M20 "
          "AND C>M5 AND M20>=REF(M20,3);"),
   detail="三角闭合于{B3:.0f}日前 MA5={M5:.2f} MA20={M20:.2f}",
   strength="(M5-M20)/M20*100")

_s("jinzhusi", "均线金蜘蛛", CAT_MA,
   "三条均线由发散收敛聚于一点后再度发散转为多头（金蜘蛛形态）：昨日三线粘合（间距≤2%），"
   "今日发散为多头排列并放量确认。",
   "用户材料《均线汇聚交叉：金三角、金蜘蛛》",
   _MA + ("SP:=MAX(M5,MAX(M10,M20))/MIN(MIN(M5,M10),M20); "
          "XG:REF(SP,1)<=1.02 AND SP>1.02 AND M5>M10 AND M10>M20 AND C>M5 "
          "AND V>=1.3*MA(V,5);"),
   detail="三线间距={SP:.4f} MA5={M5:.2f} MA20={M20:.2f}")

_s("nianhe_break", "均线粘合·放量突破", CAT_MA,
   "5/10/20 三线粘合（间距≤4%）后，放量（≥2倍5日均量）突破三线上沿，方向选择向上。",
   "通达信经典形态",
   _MA5_20 + ("UP3:=MAX(M5,MAX(M10,M20)); SP:=UP3/MIN(MIN(M5,M10),M20); VR5:=V/MA(V,5); "
              "XG:REF(SP,1)<=1.04 AND C>UP3 AND REF(C,1)<=REF(UP3,1) AND VR5>=2;"),
   detail="粘合度={SP:.4f} 量比5均={VR5:.2f}", strength="VR5")

_s("laoyatou", "老鸭头", CAT_MA,
   "5日线上穿10日线后缩量回调（鸭头下探）不破60日线，随后5日线再度金叉10日线"
   "（鸭嘴张开）——经典庄股洗盘形态。",
   "通达信经典形态",
   _MA + ("DN:=BARSLAST(CROSS(M10,M5)); "
          "XG:CROSS(M5,M10) AND DN>=5 AND DN<=40 AND LLV(C,DN)>M60 "
          "AND M60>=REF(M60,5) AND C>O;"),
   detail="回调持续{DN:.0f}日 MA60={M60:.2f}")

_s("huochegui", "火车轨·双轨上行回踩", CAT_MA,
   "20日与60日均线近似平行上行（双轨），股价回踩20日线附近获支撑收阳——趋势中继买点。",
   "通达信经典形态",
   _MA + ("XG:M20>=REF(M20,10) AND M60>=REF(M60,10) AND ABS(M20-M60)/M60<=0.08 "
          "AND L<=M20*1.02 AND C>M20 AND C>REF(C,1);"),
   detail="MA20={M20:.2f} MA60={M60:.2f}")

_s("chishuifurong", "出水芙蓉·一阳穿三线", CAT_MA,
   "一根大阳线（≥3%）开盘在5/10/20日线下方、收盘站上三线之上，一举穿越全部短中期均线。",
   "通达信经典形态",
   _MA5_20 + ("ZF:=(C/REF(C,1)-1)*100; "
              "XG:C>O AND O<MIN(MIN(M5,M10),M20) AND C>MAX(MAX(M5,M10),M20) AND ZF>=3;"),
   detail="涨幅={ZF:.2f}%", strength="ZF")

_s("ma_bias_repair", "急跌回抽·乖离修复", CAT_MA,
   "盘中急跌击穿10日线3%以上又被拉回线上，10日线仍向上——洗盘性质的乖离快速修复。",
   "通达信经典形态",
   _MA5_20 + "XG:L<=M10*0.97 AND C>M10 AND M10>=REF(M10,3) AND C>O;",
   detail="MA10={M10:.2f} 最低={L:.2f}")

# ---------- 二、MACD动能 ----------

CAT_MACD = "MACD动能"

_s("macd_gold", "MACD金叉", CAT_MACD, "DIF上穿DEA，最经典的MACD买入信号。",
   "通达信经典指标", _MACD + "XG:CROSS(DIF,DEA);",
   detail="DIF={DIF:.3f} DEA={DEA:.3f}", strength="MC")

_s("macd_gold_low", "MACD零下金叉", CAT_MACD, "零轴下方金叉，超跌后的反弹动能信号（左侧抄底类）。",
   "通达信经典指标", _MACD + "XG:CROSS(DIF,DEA) AND DIF<0;",
   detail="DIF={DIF:.3f} DEA={DEA:.3f}")

_s("macd_gold_strong", "MACD零上金叉", CAT_MACD, "零轴上方金叉，强势整理后的再度进攻（右侧趋势类）。",
   "通达信经典指标", _MACD + "XG:CROSS(DIF,DEA) AND DIF>0 AND DEA>0;",
   detail="DIF={DIF:.3f}")

_s("macd_gold_2", "MACD二次金叉", CAT_MACD,
   "30日内出现第二次金叉——第一次金叉后回调未死叉，做多动能重启。",
   "通达信经典指标", _MACD + "XG:COUNT(CROSS(DIF,DEA),30)=2 AND CROSS(DIF,DEA);",
   detail="DIF={DIF:.3f}")

_s("macd_foshou", "MACD佛手向上", CAT_MACD,
   "红柱连续缩短3日但不死叉，随后重新放大——形似佛手，多头中继经典形态。",
   "通达信经典形态",
   _MACD + "XG:DIF>DEA AND MC>REF(MC,1) AND REF(MC,1)<=REF(MC,2) "
           "AND REF(MC,2)<=REF(MC,3) AND MC>0;",
   detail="红柱={MC:.3f}")

_s("macd_red_grow", "MACD红柱三连放大", CAT_MACD, "红柱连续3日放大，上涨动能持续增强。",
   "通达信经典指标",
   _MACD + "XG:MC>0 AND MC>REF(MC,1) AND REF(MC,1)>REF(MC,2) AND REF(MC,2)>REF(MC,3);",
   detail="红柱={MC:.3f}", strength="MC")

_s("macd_div_bottom", "MACD底背离(简化)", CAT_MACD,
   "股价创60日新低附近但DIF未创新低并金叉——跌势动能衰竭的背离信号（简化判定，仅供参考）。",
   "通达信经典形态",
   _MACD + "XG:L<=LLV(L,60)*1.02 AND DIF>REF(LLV(DIF,30),1) AND CROSS(DIF,DEA);",
   detail="最低={L:.2f} DIF={DIF:.3f}")

_s("macd_zero_cross", "MACD·DIF上穿零轴", CAT_MACD, "DIF由负转正，空头动能彻底转向多头。",
   "通达信经典指标", _MACD + "XG:CROSS(DIF,0);", detail="DIF={DIF:.3f}")

_s("macd_green_shrink", "MACD绿柱三连收窄", CAT_MACD, "绿柱连续3日收窄，下跌动能衰竭，反弹将近。",
   "通达信经典指标",
   _MACD + "XG:MC<0 AND ABS(MC)<ABS(REF(MC,1)) AND ABS(REF(MC,1))<ABS(REF(MC,2)) "
           "AND ABS(REF(MC,2))<ABS(REF(MC,3));",
   detail="绿柱={MC:.3f}")

# ---------- 三、摆动指标（KDJ/RSI等） ----------

CAT_OSC = "摆动指标"

_s("kdj_gold", "KDJ金叉", CAT_OSC, "K值上穿D值，随机指标经典买入信号。",
   "通达信经典指标", _KDJ + "XG:CROSS(K,D);", detail="K={K:.1f} D={D:.1f}")

_s("kdj_gold_low", "KDJ低位金叉", CAT_OSC, "K值30以下金叉D值，超卖区反转信号，胜率高于普通金叉。",
   "通达信经典指标", _KDJ + "XG:CROSS(K,D) AND REF(K,1)<30;",
   detail="K={K:.1f} D={D:.1f}")

_s("kdj_j_reverse", "KDJ·J值超卖反转", CAT_OSC, "J值昨日小于0（深度超卖）今日拐头向上。",
   "通达信经典指标", _KDJ + "XG:REF(J,1)<0 AND J>REF(J,1);", detail="J={J:.1f}")

_s("kdj_div_bottom", "KDJ底背离(简化)", CAT_OSC,
   "股价创30日新低附近但K值未创新低——下跌动能衰竭背离（简化判定）。",
   "通达信经典形态",
   _KDJ + "XG:L<=LLV(L,30)*1.02 AND K>REF(LLV(K,30),1)+8 AND REF(K,1)<50;",
   detail="最低={L:.2f} K={K:.1f}")

_s("kdj_k_cross50", "KDJ·K值上穿50", CAT_OSC, "K值上穿50中轴，摆动指标由弱转强的确认信号。",
   "通达信经典指标", _KDJ + "XG:CROSS(K,50);", detail="K={K:.1f}")

_s("rsi_gold", "RSI金叉", CAT_OSC, "6日RSI上穿12日RSI，短周期相对强弱转强。",
   "通达信经典指标", _RSI + "XG:CROSS(RSI6,RSI12);",
   detail="RSI6={RSI6:.1f} RSI12={RSI12:.1f}")

_s("rsi_gold_low", "RSI低位金叉", CAT_OSC, "RSI低位（12日线<40）金叉，超卖反转可信度更高。",
   "通达信经典指标", _RSI + "XG:CROSS(RSI6,RSI12) AND RSI12<40;",
   detail="RSI6={RSI6:.1f} RSI12={RSI12:.1f}")

_s("rsi_oversold_rev", "RSI超卖回升", CAT_OSC, "6日RSI昨日低于20（深度超卖）今日回升。",
   "通达信经典指标", _RSI + "XG:REF(RSI6,1)<20 AND RSI6>REF(RSI6,1) AND RSI6<40;",
   detail="RSI6={RSI6:.1f}")

_s("rsi_break80", "RSI进入强势区", CAT_OSC,
   "6日RSI上穿80，进入超强区域（动量追涨型信号，需防过热）。",
   "通达信经典指标", _RSI + "XG:CROSS(RSI6,80);", detail="RSI6={RSI6:.1f}")

_s("bias_low", "BIAS乖离超卖反弹", CAT_OSC,
   "12日乖离率低于阈值（默认-8%）后收阳反弹，超跌修复。阈值可调。",
   "通达信经典指标",
   "BL:=(C/MA(C,12)-1)*100; XG:BL<=-N AND C>REF(C,1) AND C>O;",
   detail="乖离率={BL:.2f}%",
   params=[ParamDef("n", "乖离率阈值", "number", 8.0, 3, 25, 0.5, "%",
                    "12日乖离率低于该值（取负）视为超跌")])

_s("wr_oversold_rev", "WR威廉超卖回头", CAT_OSC,
   "威廉指标昨日≥80（超卖区）今日回落离开超卖区，短线反弹启动。",
   "通达信经典指标",
   _WR + "XG:REF(WR10,1)>=80 AND WR10<80;", detail="WR10={WR10:.1f}")

_s("cci_oversold", "CCI上穿-100", CAT_OSC, "顺势指标从超卖区上穿-100，回归常态区间的启动点。",
   "通达信经典指标", _CCI + "XG:CROSS(CCI,-100);", detail="CCI={CCI:.1f}")

_s("cci_break100", "CCI上穿100", CAT_OSC, "顺势指标上穿+100，进入强势区间（动量型信号）。",
   "通达信经典指标", _CCI + "XG:CROSS(CCI,100);", detail="CCI={CCI:.1f}")

_s("psy_low", "PSY人气超卖回升", CAT_OSC, "12日心理线低于25（市场极度悲观）后收阳，情绪修复。",
   "通达信经典指标", _PSY + "XG:REF(PSY,1)<25 AND C>REF(C,1);", detail="PSY={PSY:.1f}")

_s("mtm_gold", "动量MTM金叉", CAT_OSC, "12日动量线上穿其6日均线，价格动量转正加速。",
   "通达信经典指标",
   "MTM:=C-REF(C,12); MMA:=MA(MTM,6); XG:CROSS(MTM,MMA);", detail="MTM={MTM:.2f}")

# ---------- 四、BOLL轨道 ----------

CAT_BOLL = "BOLL轨道"

_s("boll_low_support", "BOLL下轨支撑", CAT_BOLL, "盘中跌破下轨后收回轨上并收阳，轨道支撑有效。",
   "通达信经典指标",
   _BOLL + "XG:L<=LOWR AND C>LOWR AND C>O;", detail="下轨={LOWR:.2f} 收盘={C:.2f}")

_s("boll_mid_break", "BOLL突破中轨", CAT_BOLL, "收盘价自下而上突破20日中轨，回归强势半区。",
   "通达信经典指标", _BOLL + "XG:CROSS(C,MID);", detail="中轨={MID:.2f}")

_s("boll_up_break", "BOLL放量突破上轨", CAT_BOLL, "放量（≥2倍5日均量）突破布林上轨，超强启动。",
   "通达信经典指标",
   _BOLL + "VR5:=V/MA(V,5); XG:CROSS(C,UPR) AND VR5>=2;",
   detail="上轨={UPR:.2f} 量比5均={VR5:.2f}", strength="VR5")

_s("boll_ride_up", "BOLL上轨强势骑行", CAT_BOLL,
   "连续两日收于上轨上方且上轨向上——沿轨强势上行，趋势极强。",
   "通达信经典指标",
   _BOLL + "XG:C>UPR AND REF(C,1)>REF(UPR,1) AND UPR>=REF(UPR,1);",
   detail="上轨={UPR:.2f}")

_s("boll_squeeze_open", "BOLL收口突破", CAT_BOLL,
   "布林带宽处于60日最低附近（极度收口）后开口向上，配合放量站上中轨——变盘方向向上。",
   "通达信经典指标",
   _BOLL + ("BW:=(UPR-LOWR)/MID; VR5:=V/MA(V,5); "
            "XG:REF(BW,1)<=LLV(BW,60)*1.05 AND C>MID AND VR5>=1.5 AND UPR>=REF(UPR,1);"),
   detail="带宽={BW:.3f} 量比5均={VR5:.2f}")

_s("boll_mid_hold", "BOLL升势回踩中轨", CAT_BOLL,
   "中轨上行途中回踩中轨不破收阳——轨道趋势中继买点。",
   "通达信经典指标",
   _BOLL + "XG:MID>=REF(MID,20) AND L<=MID*1.01 AND C>MID AND C>REF(C,1);",
   detail="中轨={MID:.2f}")

_s("boll_strong_pullback", "BOLL强势回踩中轨", CAT_BOLL,
   "近20日曾突破布林上轨（强势确认）且20日内最低价始终不破中轨（沿轨上行），"
   "当前价回落至中轨附近（乖离≤3%）——强势股回踩中轨低吸。",
   "用户提供通达信公式",
   _BOLL + ("PL:=(C/MID-1)*100; "
            "XG:EXIST(C>UPR,20) AND EVERY(L>=MID,20) AND ABS(PL)<=3;"),
   detail="距中轨={PL:.2f}% 中轨={MID:.2f}")

_s("boll_low_narrow", "BOLL低位极度收口", CAT_BOLL,
   "带宽接近60日最低且股价处于近半年低位区（40%以下）——变盘临近的潜伏信号。",
   "通达信经典指标",
   _BOLL + _POS + "BW:=(UPR-LOWR)/MID; "
   "XG:REF(BW,1)<=LLV(BW,60)*1.1 AND POS<=0.4;",
   detail="带宽={BW:.3f} 区间位置={POS:.2f}")

# ---------- 五、量价关系 ----------

CAT_VOL = "量价关系"

_s("vol_break_20", "放量突破20日新高", CAT_VOL,
   "收盘价创20日新高且成交量≥2倍5日均量——平台突破确认。",
   "通达信经典量价",
   "VR5:=V/MA(V,5); HV:=HHV(REF(H,1),20); XG:C>=HV AND VR5>=2;",
   detail="20日高={HV:.2f} 量比5均={VR5:.2f}", strength="VR5")

_s("vol_break_60", "放量突破60日新高", CAT_VOL,
   "收盘价创60日新高且成交量≥2倍5日均量——中期突破。",
   "通达信经典量价",
   "VR5:=V/MA(V,5); HV:=HHV(REF(H,1),60); XG:C>=HV AND VR5>=2;",
   detail="60日高={HV:.2f} 量比5均={VR5:.2f}", strength="VR5")

_s("vol_shrink_pullback", "升势缩量回调", CAT_VOL,
   "多头排列中缩量（≤7成5日均量）回调至10日线附近——主力未出逃的良性洗盘。",
   "通达信经典量价",
   _MA5_20 + ("VR5:=V/MA(V,5); "
              "XG:M5>M10 AND M10>M20 AND C<REF(C,1) AND VR5<0.7 "
              "AND C>=M10*0.97 AND C<=M10*1.03;"),
   detail="量缩比={VR5:.2f} MA10={M10:.2f}")

_s("vol_diliang", "地量出现", CAT_VOL,
   "成交量接近60日最低且近60日振幅已收敛至35%以内——「地量见地价」的底部区域信号。",
   "通达信经典量价",
   "ZF:=(HHV(H,60)-LLV(L,60))/(LLV(L,60)+0.0001); ZFP:=ZF*100; "
   "XG:V<=LLV(V,60)*1.02 AND ZF<0.35;",
   detail="60日振幅={ZFP:.1f}%")

_s("vol_price_up", "量价齐升", CAT_VOL,
   "连续两日价升量增且收阳——资金持续流入的标准量价配合。",
   "通达信经典量价",
   "Z2:=(C/REF(C,2)-1)*100; "
   "XG:C>REF(C,1) AND V>REF(V,1) AND REF(C,1)>REF(C,2) AND REF(V,1)>REF(V,2) AND C>O;",
   detail="两日涨幅={Z2:.2f}%")

_s("vol_double_yang", "倍量阳线", CAT_VOL,
   "成交量较昨日翻倍且收阳收涨——新增资金大举介入的标志。",
   "通达信经典量价",
   "VL:=V/REF(V,1); XG:VL>=2 AND C>O AND C>REF(C,1);",
   detail="量比昨日={VL:.2f}", strength="VL")

_s("vol_three_up", "三日量价温和齐升", CAT_VOL,
   "连续三日价升量增——温和放量、健康上涨结构。",
   "通达信经典量价",
   "Z3:=(C/REF(C,3)-1)*100; XG:EVERY(C>REF(C,1),3) AND EVERY(V>REF(V,1),3);",
   detail="三日涨幅={Z3:.2f}%")

_s("vol_obv_gold", "OBV上穿30日线", CAT_VOL,
   "能量潮上穿其30日均线，累积能量由负转正。",
   "通达信经典指标",
   _OBV + "XG:CROSS(OBV,MA(OBV,30));", detail="OBV={OBV:.0f}")

_s("vol_obv_lead", "OBV先行创新高", CAT_VOL,
   "OBV创60日新高而价格尚未创新高——「量先价行」，主力建仓充分的领先信号。",
   "通达信经典量价",
   _OBV + "OBVH:=HHV(OBV,60); XG:OBV>=OBVH AND C<HHV(H,60)*0.98;",
   detail="OBV={OBV:.0f} 60日OBV高={OBVH:.0f}")

_s("vol_vr_low", "VR低位上穿", CAT_VOL,
   "成交量比率VR自低位上穿70，买方动能开始占优。",
   "通达信经典指标",
   _VR + "XG:CROSS(VR,70);", detail="VR={VR:.1f}")

_s("vol_amount_high", "放量大阳·成交额创高", CAT_VOL,
   "成交额创30日新高且收出5%以上大阳线——市场关注度与资金共振。",
   "通达信经典量价",
   "AE:=AMOUNT/1e8; XG:AMOUNT>=HHV(AMOUNT,30) AND C/REF(C,1)>=1.05 AND C>O;",
   detail="成交额={AE:.2f}亿")

_s("vol_shrink_stable", "极度缩量·趋势未坏", CAT_VOL,
   "成交量缩至5日均量35%以下而20日线仍上行——洗盘尾声的变盘前夜。",
   "通达信经典量价",
   _MA5_20 + "VR5:=V/MA(V,5); XG:VR5<=0.35 AND M20>=REF(M20,10);",
   detail="量缩比={VR5:.2f}")

_s("vol_cross_ma5", "放量站上5日线", CAT_VOL,
   "放量（≥1.8倍5日均量）收盘上穿5日线且5日线拐头向上。",
   "通达信经典量价",
   _MA5_20 + "VR5:=V/MA(V,5); XG:CROSS(C,M5) AND VR5>=1.8 AND M5>=REF(M5,3);",
   detail="量比5均={VR5:.2f}", strength="VR5")

# ---------- 六、K线形态 ----------

CAT_KBAR = "K线形态"

_s("morning_star", "早晨之星", CAT_KBAR,
   "大阴线→低开小星线→阳线收复前阴实体一半——经典三K线底部反转形态。",
   "通达信经典形态",
   "XX:=(REF(C,1)-REF(O,1))/(REF(C,2)+0.0001)*100; "
   "XG:REF(C,2)/REF(O,2)<=0.97 AND ABS(REF(C,1)-REF(O,1))/(REF(C,2)+0.0001)<=0.012 "
   "AND REF(C,1)<REF(O,2)*1.01 AND C>O AND C>=(REF(O,2)+REF(C,2))/2;",
   detail="星线实体={XX:.2f}%")

_s("shuguang", "曙光初现", CAT_KBAR,
   "阴线之后阳线切入其实体一半以上——多头反攻的第一日信号。",
   "通达信经典形态",
   "ZY:=(REF(C,1)/REF(C,2)-1)*100; "
   "XG:REF(C,1)<REF(O,1) AND REF(C,1)/REF(C,2)<=0.97 AND C>O AND C>=(REF(O,1)+REF(C,1))/2;",
   detail="昨日跌幅={ZY:.2f}%")

_s("xuri", "旭日东升", CAT_KBAR,
   "阴线后跳空高开收大阳且收盘高于昨日开盘价——比曙光初现更强的反转形态。",
   "通达信经典形态",
   "TK:=(O/REF(C,1)-1)*100; XG:REF(C,1)<REF(O,1) AND O>REF(C,1) AND C>O AND C>REF(O,1);",
   detail="跳空幅度={TK:.2f}%")

_s("red_three", "红三兵", CAT_KBAR,
   "连续三根阳线依次上行——温和而坚定的底部启动形态。",
   "通达信经典形态",
   "Z3:=(C/REF(C,3)-1)*100; XG:EVERY(C>O AND C>REF(C,1),3);",
   detail="三日涨幅={Z3:.2f}%")

_s("yangbaoyin", "阳包阴·看涨吞没", CAT_KBAR,
   "阳线实体完全包裹昨日阴线实体——多头力量逆转。",
   "通达信经典形态",
   "STZ:=(C-O)/O*100; XG:REF(C,1)<REF(O,1) AND C>O AND C>=REF(O,1) AND O<=REF(C,1);",
   detail="阳线实体占比={STZ:.2f}%")

_s("hammer_low", "低位锤头线", CAT_KBAR,
   "60日低位区出现长下影小实体锤头（下影≥振幅55%）——空头打压被多头承接。",
   "通达信经典形态",
   _KBAR + _POS + "XG:POS<=0.3 AND LOSP>=0.55 AND REAL<=0.25 AND UPSP<=0.15 AND C>O;",
   detail="区间位置={POS:.2f} 下影占比={LOSP:.2f}")

_s("inv_hammer_low", "低位倒锤头", CAT_KBAR,
   "60日低位区出现长上影小实体倒锤头——试探上方抛压后的反转信号（次日需确认）。",
   "通达信经典形态",
   _KBAR + _POS + "XG:POS<=0.3 AND UPSP>=0.55 AND REAL<=0.25 AND LOSP<=0.15;",
   detail="区间位置={POS:.2f} 上影占比={UPSP:.2f}")

_s("doji_low", "低位长十字星", CAT_KBAR,
   "60日低位区的长十字星（实体占比≤6%、振幅≥2.5%）——多空平衡待变盘。",
   "通达信经典形态",
   _KBAR + _POS + "ZFD:=RG/(REF(C,1)+0.0001)*100; XG:POS<=0.3 AND REAL<=0.06 AND ZFD>=2.5;",
   detail="区间位置={POS:.2f} 振幅={ZFD:.2f}%")

_s("strong_close", "长下影强势收盘", CAT_KBAR,
   "长下影（≥40%振幅）阳线且收盘位于当日振幅上3/4——尾盘强力承接。",
   "通达信经典形态",
   _KBAR + "CW:=(C-L)/RG; XG:LOSP>=0.4 AND C>O AND CW>=0.75;",
   detail="收盘位置={CW:.2f}")

_s("rub_line_low", "低位揉搓线(看涨)", CAT_KBAR,
   "先上影T形线、后下影T形线的K线组合并配合缩量（如材料所述为「揉搓线」洗盘）。"
   "材料指出：出现在相对低位时是锤头线与倒锤头线的组合，看涨信号，之后往往迎来主升段急升行情。",
   "用户材料《揉搓线》K线组合",
   _KBAR + _POS + ("UT:=REF(UPSP>=0.6 AND REAL<=0.2,1); VR5:=V/MA(V,5); "
                   "XG:UT AND LOSP>=0.6 AND REAL<=0.2 AND VR5<1 AND POS<=0.45;"),
   detail="区间位置={POS:.2f} 量比5均={VR5:.2f}")

_s("limit_up", "涨停板", CAT_KBAR,
   "收盘涨停（涨幅≥9.7%且收于最高价；主板口径近似，20cm股按同样规则自然覆盖）。",
   "通达信经典形态",
   _ZT + "ZF:=(C/REF(C,1)-1)*100; XG:ZT;", detail="涨幅={ZF:.2f}%",
   strength="(C/REF(C,1)-1)*100")

_s("limit_2", "二连板", CAT_KBAR,
   "连续两个涨停——强势股加速的标志（打板策略基础信号）。",
   "通达信经典形态",
   _ZT + "Z2:=(C/REF(C,2)-1)*100; XG:EVERY(ZT,2);", detail="两日涨幅={Z2:.2f}%")

_s("limit_3", "三连板", CAT_KBAR,
   "连续三个涨停——极强的资金合力，龙头股特征。",
   "通达信经典形态",
   _ZT + "Z3:=(C/REF(C,3)-1)*100; XG:EVERY(ZT,3);", detail="三日涨幅={Z3:.2f}%")

_s("limit_yesterday", "昨日涨停·今日缩量上攻", CAT_KBAR,
   "昨日涨停、今日未回落且缩量上攻——涨停后洗盘充分的接力信号。",
   "通达信经典形态",
   _ZT + "Z2:=(C/REF(C,2)-1)*100; XG:REF(ZT,1) AND V<REF(V,1) AND C>REF(C,1);",
   detail="两日累计={Z2:.2f}%")

_s("gap_up", "向上跳空缺口", CAT_KBAR,
   "今日最低价高于昨日最高价——形成未回补的向上跳空缺口。",
   "通达信经典形态",
   "QK:=(L/REF(H,1)-1)*100; XG:L>REF(H,1);", detail="缺口幅度={QK:.2f}%")

_s("gap_up_2", "双跳空缺口", CAT_KBAR,
   "连续两日向上跳空——极端强势（注意高位双缺口的回补风险）。",
   "通达信经典形态",
   "QK:=(L/REF(H,1)-1)*100; XG:L>REF(H,1) AND REF(L,1)>REF(H,2);",
   detail="缺口幅度={QK:.2f}%")

_s("n_shape", "N字涨停·回调再起", CAT_KBAR,
   "涨停后缩量回调2~9日不破涨停起点，今日再收阳——N字上攻结构成型。",
   "通达信经典形态",
   _ZT + ("LZ:=BARSLAST(ZT); "
          "XG:LZ>=3 AND LZ<=10 AND LLV(C,LZ)>=REF(C,LZ+1)*0.96 AND REF(V,1)<MA(V,5) "
          "AND C>O AND C>REF(C,1);"),
   detail="涨停在{LZ:.0f}日前")

_s("zt_pullback_ma5", "涨停回踩5日线", CAT_KBAR,
   "涨停后2~8日缩量回踩5日线获支撑——强势股的第二买点。",
   "通达信经典形态",
   _MA5_20 + _ZT + ("LZ:=BARSLAST(ZT); "
                    "XG:LZ>=2 AND LZ<=8 AND L<=M5*1.02 AND C>M5 AND V<REF(V,1);"),
   detail="涨停在{LZ}日前 MA5={M5:.2f}")

_s("three_low_tail", "低位三连下影", CAT_KBAR,
   "60日低位连续三日长下影（下影≥40%振幅）——下方承接盘密集，筑底信号。",
   "通达信经典形态",
   _KBAR + _POS + "XG:EVERY(LOSP>=0.4,3) AND POS<=0.35;",
   detail="区间位置={POS:.2f}")

_s("pingdi", "平底双日", CAT_KBAR,
   "昨日阴线今日阳线且两日最低价几乎相同（差异≤0.2%）——下方支撑精确到位。",
   "通达信经典形态",
   "LY:=REF(L,1); XG:ABS(L-LY)/(REF(C,1)+0.0001)<=0.002 AND C>REF(C,1) AND REF(C,1)<REF(O,1);",
   detail="两日低点={L:.2f} 与 {LY:.2f}")

# ---------- 七、缠论结构（简化实现） ----------

CAT_CHAN = "缠论结构(简化)"

_s("chan_fd_bottom", "缠论·底分型", CAT_CHAN,
   "三根K线中中间一根低点为三者最低（简化：忽略包含关系处理）——缠论最小级别的底部结构单元。",
   "缠论（简化量化）",
   "FL:=REF(L,1); "
   "XG:FL<REF(L,2) AND FL<L AND REF(H,1)<REF(H,2) AND REF(H,1)<H;",
   detail="分型低点={FL:.2f}")

_s("chan_fd_top", "缠论·顶分型(风险)", CAT_CHAN,
   "中间一根K线高点为三者最高——顶部结构单元，持仓预警（选股中可用于排除）。",
   "缠论（简化量化）",
   "FH:=REF(H,1); "
   "XG:FH>REF(H,2) AND FH>H AND REF(L,1)>REF(L,2) AND REF(L,1)>L;",
   detail="分型高点={FH:.2f}")

_s("chan_1buy", "缠论·一买(背驰底分型)", CAT_CHAN,
   "下跌背驰段的底分型确认：股价创60日新低附近、DIF未创新低（背驰）且DIF<0，"
   "随后出现底分型——缠论第一类买点的简化实现。",
   "缠论（简化量化）",
   _MACD + ("FL:=REF(L,1); FD1:=REF(DIF,1); "
            "XG:FL<REF(L,2) AND FL<L AND FL<=LLV(L,60)*1.02 "
            "AND FD1>LLV(DIF,60)*1.05 AND FD1<0;"),
   detail="分型低点={FL:.2f} 前日DIF={FD1:.3f}")

_s("chan_2buy", "缠论·二买(回调不破前低)", CAT_CHAN,
   "一买后次级别回调不再创新低并再度出现底分型——缠论第二类买点的简化实现。",
   "缠论（简化量化）",
   _MACD + ("FL:=REF(L,1); FD:=FL<REF(L,2) AND FL<L; "
            "YM:=FD AND FL<=LLV(L,60)*1.02; "
            "FDL:=VALUEWHEN(YM,FL); BY:=BARSLAST(YM); "
            "XG:FD AND FL>FDL AND BY>=3 AND BY<=30;"),
   detail="一买低点={FDL:.2f} 距一买{BY:.0f}日")

_s("chan_3buy", "缠论·三买(中枢突破回踩)", CAT_CHAN,
   "放量突破60日箱体（中枢）后回踩不破箱体上沿——缠论第三类买点的简化实现。",
   "缠论（简化量化）",
   "LV0:=HHV(REF(H,1),60); BRK:=CROSS(C,LV0); LV:=VALUEWHEN(BRK,LV0); BT:=BARSLAST(BRK); "
   "XG:BT>=3 AND BT<=15 AND LLV(L,BT)>=LV*0.97 AND C>LV AND C>REF(C,1);",
   detail="中枢上沿={LV:.2f} 突破于{BT:.0f}日前")

_s("chan_box_low", "缠论·中枢下沿低吸", CAT_CHAN,
   "近40日构成振幅≤30%的横盘箱体（中枢）且未持续下移，股价回踩箱体下沿收阳低吸。",
   "缠论（简化量化）",
   "UPP:=HHV(H,40); DNN:=LLV(L,40); "
   "XG:(UPP-DNN)/(DNN+0.0001)<=0.3 AND L<=DNN*1.03 AND C>DNN AND C>O "
   "AND DNN>=REF(DNN,20)*0.97;",
   detail="箱体下沿={DNN:.2f} 上沿={UPP:.2f}")

# ---------- 八、趋势突破 ----------

CAT_TREND = "趋势突破"

_s("donchian_20", "唐奇安20日突破", CAT_TREND,
   "收盘价突破前20日最高价——海龟交易法则入场信号。",
   "海龟交易法则",
   "HV:=HHV(REF(H,1),20); XG:C>=HV;", detail="20日高={HV:.2f}")

_s("donchian_55", "唐奇安55日突破", CAT_TREND,
   "收盘价突破前55日最高价——海龟系统中长周期入场。",
   "海龟交易法则",
   "HV:=HHV(REF(H,1),55); XG:C>=HV;", detail="55日高={HV:.2f}")

_s("high_60", "创60日新高", CAT_TREND,
   "收盘价创60日新高，上方无套牢盘。",
   "通达信经典形态",
   "HV:=HHV(REF(H,1),60); XG:C>=HV;", detail="60日高={HV:.2f}")

_s("high_250", "创一年新高", CAT_TREND,
   "收盘价创250日新高——历史套牢盘全面消化（需约一年以上本地数据）。",
   "通达信经典形态",
   "HV:=HHV(REF(H,1),250); XG:C>=HV;", detail="250日高={HV:.2f}")

_s("platform_break", "平台突破", CAT_TREND,
   "近20日振幅≤15%的窄幅横盘平台（截至昨日），今日放量突破平台上沿。",
   "通达信经典形态",
   "PV:=REF(HHV(H,20),1); ZF20:=REF((HHV(H,20)-LLV(L,20))/(LLV(L,20)+0.0001),1); "
   "VR5:=V/MA(V,5); XG:ZF20<=0.15 AND C>PV AND VR5>=2;",
   detail="平台高={PV:.2f} 量比5均={VR5:.2f}", strength="VR5")

_s("turtle_trend", "海龟突破·趋势过滤", CAT_TREND,
   "唐奇安20日突破 + 20日线在60日线上方且向上——双重趋势过滤，减少假突破。",
   "海龟交易法则（改良）",
   _MA + "HV:=HHV(REF(H,1),20); XG:C>=HV AND M20>M60 AND M20>=REF(M20,10);",
   detail="20日高={HV:.2f} MA20={M20:.2f}")

_s("sar_turn", "SAR翻红", CAT_TREND,
   "收盘价自下而上穿越抛物线SAR——止损转向系统发出的做多信号。",
   "通达信经典指标",
   "S:=SAR(10,2,20); XG:C>S AND REF(C,1)<=REF(S,1);",
   detail="SAR={S:.2f} 收盘={C:.2f}")

_s("ma60_break_up", "放量突破60日线", CAT_TREND,
   "收盘价上穿60日线且60日线走平上行——中期趋势突破。",
   "通达信经典形态",
   _MA5_20 + "M60:=MA(C,60); XG:CROSS(C,M60) AND M60>=REF(M60,5);",
   detail="MA60={M60:.2f}")

_s("trend_accel", "均线加速上行", CAT_TREND,
   "5日线3日斜率≥2%且持续加速、价格站上5日线且高于60日线。",
   "通达信经典形态",
   _MA + "XL:=(M5/REF(M5,3)-1)*100; XG:M5>=REF(M5,3)*1.02 AND REF(M5,3)>=REF(M5,6)*1.02 "
         "AND C>M5 AND M5>M60;",
   detail="MA5={M5:.2f} 3日斜率={XL:.2f}%")

# ---------- 九、多条件共振 ----------

CAT_RES = "多条件共振"

_s("res_ma_macd", "均线+MACD双金叉", CAT_RES,
   "近3日内MACD金叉，今日均线5上穿10——两个独立体系同时转多。",
   "通达信组合公式",
   _MA5_20 + _MACD + "XG:CROSS(M5,M10) AND COUNT(CROSS(DIF,DEA),3)>=1;",
   detail="MA5={M5:.2f} DIF={DIF:.3f}")

_s("res_macd_kdj", "MACD+KDJ双金叉", CAT_RES,
   "近3日内MACD与KDJ先后金叉——趋势与摆动指标共振。",
   "通达信组合公式",
   _MACD + _KDJ + "XG:COUNT(CROSS(DIF,DEA),3)>=1 AND COUNT(CROSS(K,D),3)>=1;",
   detail="K={K:.1f} DIF={DIF:.3f}")

_s("res_triple_cross", "三金叉共振", CAT_RES,
   "价金叉（5上穿10）+ 量金叉（5日均量上穿10日均量）+ MACD金叉在3日内齐现——"
   "经典「三金叉」启动模型。",
   "通达信组合公式",
   _MA5_20 + _MACD + ("XG:COUNT(CROSS(M5,M10),3)>=1 "
                      "AND COUNT(CROSS(MA(V,5),MA(V,10)),3)>=1 "
                      "AND COUNT(CROSS(DIF,DEA),3)>=1;"),
   detail="MA5={M5:.2f} DIF={DIF:.3f}")

_s("res_boll_rsi", "BOLL下轨+RSI超卖共振", CAT_RES,
   "触及布林下轨且RSI6<25后收涨——双重超卖共振反弹。",
   "通达信组合公式",
   _BOLL + _RSI + "XG:L<=LOWR AND RSI6<25 AND C>REF(C,1);",
   detail="RSI6={RSI6:.1f} 下轨={LOWR:.2f}")

_s("res_all_bull", "全多头共振", CAT_RES,
   "均线多头 + MACD红柱 + KDJ金叉状态 + 站上5日线——四大体系同时处于多头状态。",
   "通达信组合公式",
   _MA + _MACD + _KDJ +
   "XG:M5>M10 AND M10>M20 AND M20>M60 AND DIF>DEA AND K>D AND C>M5;",
   detail="MA5={M5:.2f} 柱={MC:.3f}")

_s("res_oversold_rebound", "超跌反弹共振", CAT_RES,
   "60日跌幅≥阈值后放量长阳站上5日线——超跌+启动信号组合。跌幅阈值可调。",
   "通达信组合公式",
   _MA5_20 + ("DC:=(C/REF(C,60)-1)*100; "
              "XG:DC<=-N AND CROSS(C,M5) AND V>=1.5*MA(V,5) AND C>O;"),
   detail="60日涨幅={DC:.1f}%",
   params=[ParamDef("n", "60日跌幅阈值", "number", 25.0, 5, 60, 1, "%",
                    "60日累计跌幅超过该值视为超跌")])

_s("res_limit_trend", "涨停+多头排列", CAT_RES,
   "昨日涨停且今日保持5>10>20日线多头排列、站上5日线。",
   "通达信组合公式",
   _MA5_20 + _ZT + "XG:REF(ZT,1) AND M5>M10 AND M10>M20 AND C>M5;",
   detail="MA5={M5:.2f} 昨日涨停")

_s("res_wr_rsi", "WR+RSI超卖双共振", CAT_RES,
   "威廉指标超卖回升叠加RSI6<25——双摆动指标同时超卖反弹。",
   "通达信组合公式",
   _WR + _RSI + "XG:REF(WR10,1)>=80 AND RSI6<25 AND C>REF(C,1);",
   detail="WR10={WR10:.1f} RSI6={RSI6:.1f}")

_s("res_gap_ma", "缺口+均线多头", CAT_RES,
   "向上跳空缺口叠加均线多头排列并放量——强势中继缺口。",
   "通达信组合公式",
   _MA5_20 + "QK:=(L/REF(H,1)-1)*100; XG:L>REF(H,1) AND M5>M10 AND M10>M20 AND V>=1.5*MA(V,5);",
   detail="缺口幅度={QK:.2f}%")

_s("res_kdj_boll_mid", "KDJ金叉+中轨上方", CAT_RES,
   "KDJ低位金叉且收盘站上布林中轨——摆动反转与趋势回归双重确认。",
   "通达信组合公式",
   _BOLL + _KDJ + "XG:CROSS(K,D) AND REF(K,1)<40 AND C>MID;",
   detail="K={K:.1f} 中轨={MID:.2f}")

# ---------- 十、风险提示 ----------

CAT_RISK = "风险提示"

_s("risk_fd_top", "顶分型预警", CAT_RISK,
   "缠论顶分型出现——持仓者警惕（可用于从候选中排除刚出顶分型的股票）。",
   "缠论（简化量化）",
   "FH:=REF(H,1); XG:FH>REF(H,2) AND FH>H AND REF(L,1)>REF(L,2) AND REF(L,1)>L;",
   detail="顶分型高点={FH:.2f}")

_s("risk_duandao", "断头铡刀", CAT_RISK,
   "一根大阴线（≥5%）同时跌破5/10/20三线——典型的趋势破坏信号，务必规避。",
   "通达信经典形态",
   _MA5_20 + ("UP3:=MAX(M5,MAX(M10,M20)); DN3:=MIN(MIN(M5,M10),M20); "
              "ZF:=(C/REF(C,1)-1)*100; "
              "XG:C<O AND O>UP3 AND C<DN3 AND ZF<=-5;"),
   detail="跌幅={ZF:.2f}%")

_s("risk_rub_high", "高位揉搓线(看跌)", CAT_RISK,
   "揉搓线组合出现在60日区间高位（70%以上）——如材料所述为上吊线+射击之星的组合，"
   "看跌信号，建议规避。",
   "用户材料《揉搓线》K线组合",
   _KBAR + _POS + ("UT:=REF(UPSP>=0.6 AND REAL<=0.2,1); "
                   "XG:UT AND LOSP>=0.6 AND REAL<=0.2 AND POS>=0.7;"),
   detail="区间位置={POS:.2f}（高位）")

_s("risk_pv_div", "价量顶背离", CAT_RISK,
   "股价创20日新高但成交量明显萎缩（<8成5日均量）——量价背离，上攻动能不足。",
   "通达信经典量价",
   "VR5:=V/MA(V,5); XG:C>=HHV(REF(H,1),20) AND VR5<0.8;",
   detail="量缩比={VR5:.2f}")

_s("risk_macd_div", "MACD顶背离(简化)", CAT_RISK,
   "股价创40日新高而DIF未同步创新高——上涨动能背离预警（简化判定）。",
   "通达信经典形态",
   _MACD + "DH:=HHV(DIF,40); XG:C>=HHV(REF(H,1),40) AND DIF<DH*0.9 AND DIF>0;",
   detail="DIF={DIF:.3f} 40日DIF高={DH:.3f}")

# ---------- 十一、游资打法（用户提供公式移植） ----------

CAT_HOT = "游资打法"

# 原文《游资进场》完整移植：X_2 为 21 项加权平滑主力线（权重 20..2、末项 REF 20），
# 信号 = 大阳(默认>8%)一举收复全部均线系统（30/45/60/90/120 日线组）+ 主力线，
# 昨日尚在主力线下方或贴线（启动前夜），且开盘未大幅高开（<3.5%，排除一字板买不进）。
_s("youzijinchang", "游资进场", CAT_HOT,
   "大阳线（涨幅>8%，可调）收盘同时站上 30/45/60/90/120 日均线组与加权主力线，"
   "而昨日尚在主力线下方或贴线徘徊——游资启动首日形态；开盘高开须小于 3.5%（排除一字板无法介入）。",
   "用户提供通达信公式《游资进场》",
   ("X1:=(3*C+L+O+H)/6; "
    "X2:=(20*X1+19*REF(X1,1)+18*REF(X1,2)+17*REF(X1,3)+16*REF(X1,4)+15*REF(X1,5)"
    "+14*REF(X1,6)+13*REF(X1,7)+12*REF(X1,8)+11*REF(X1,9)+10*REF(X1,10)+9*REF(X1,11)"
    "+8*REF(X1,12)+7*REF(X1,13)+6*REF(X1,14)+5*REF(X1,15)+4*REF(X1,16)+3*REF(X1,17)"
    "+2*REF(X1,18)+REF(X1,20))/210; "
    "X3:=MA(X2,6); "
    "X4:=MAX(MA(C,60),MA(C,120)); "
    "X5:=MAX(MA(C,45),MA(C,90)); "
    "X6:=MAX(MA(C,30),MA(C,60)); "
    "ZF:=(C/REF(C,1)-1)*100; "
    "XG:C>X6 AND C>X5 AND C>=X4 AND C>X2 "
    "AND REF(C<X3 OR (X2>=C AND C>=X3),1) "
    "AND ZF>N AND O/REF(C,1)<1.035;"),
   detail="涨幅={ZF:.2f}% 主力线={X2:.2f} 收盘={C:.2f}",
   strength="ZF",
   params=[ParamDef("n", "阳线涨幅阈值", "number", 8.0, 3, 15, 0.5, "%",
                    "当日涨幅超过该值视为游资进攻大阳")])

# 原文《尾盘2:30找票·双阴等阳》完整移植（变量改用公式内定义名）：
# 大涨(>7%) → 连续两根小阴线(实体<5%)洗盘不破位，且 MACD 多头动能、全均线多头排列，
# 第三日收阳即为「双阴等阳」——尾盘 14:30 前后介入的短线打法。
_s("shuangyindengyang", "双阴等阳·尾盘伏击", CAT_HOT,
   "2 日前大涨（>7%，可调）后连续两根小阴线（实体<5%，可调）洗盘，MACD 红柱扩张、"
   "5>10>20>60>120 全均线多头排列，今日收阳——「双阴等阳」，尾盘 2:30 伏击打法。",
   "用户提供通达信公式《尾盘2:30找票·双阴等阳》",
   ("TDZB:=REF((C-REF(C,1))/REF(C,1)*100>N1,2) AND REF(O>C AND (O-C)/C*100<N2,1) "
    "AND O>C AND (O-C)/C*100<N2; "
    "DIFF:=EMA(C,12)-EMA(C,26); DEA:=EMA(DIFF,9); "
    "TDZB1:=DIFF>0 AND DIFF>DEA AND DIFF>REF(DIFF,1) AND DEA>REF(DEA,1); "
    "DUOTOU:=MA(C,5)>MA(C,10) AND MA(C,10)>MA(C,20) AND MA(C,20)>MA(C,60) "
    "AND MA(C,60)>MA(C,120) AND MA(C,120)>REF(MA(C,120),1) AND MA(C,5)>REF(MA(C,5),1); "
    "SYMF:=TDZB AND TDZB1 AND DUOTOU; "
    "XG:REF(SYMF,1) AND C>O;"),
   detail="DIFF={DIFF:.3f} DEA={DEA:.3f}",
   strength="DIFF-DEA",
   params=[ParamDef("n1", "启动日涨幅阈值", "number", 7.0, 3, 15, 0.5, "%",
                    "2 日前那根启动大阳的最小涨幅"),
           ParamDef("n2", "洗盘阴线实体上限", "number", 5.0, 1, 10, 0.5, "%",
                    "两根洗盘阴线的实体上限（收盘-开盘的跌幅百分比）")])

# ---------- 十二、资金监控（日K近似口径，用户提供公式移植） ----------

CAT_ZIJIN = "资金监控(近似)"

# 原文《机构资金拉升选股》日K口径移植。两处近似（原文按分笔/盘中口径设计，日K上失真）：
# 1) 机构/散户日划分：原文 CJE/8>20（≈1.6万元）过松，改为"单日成交额阈值"（默认5000万）可调；
# 2) 原文 DYNAINFO(16)*10 为盘中数据不可得，超大放量阳线近似为 3 倍 5 日均量。
# 逻辑：累计"机构日"成交额占主导（净占比>18 且 机构买占比-散户卖占比>18），
#       且今日同时刷新"放量阳线次数"与"超大放量次数"并收盘价上穿累计均价地线——机构拉升启动。
_s("zijin_lasheng", "机构拉升·资金监控(近似)", CAT_ZIJIN,
   "累计机构日成交额占比占主导（机构净占比>18、机构买-散户卖>18，阈值可调），"
   "今日放量阳线（≥N倍5日均量，可调）并上穿累计均价线（地线）——机构资金拉升启动信号。"
   "注：原文按分笔口径设计（CJE/8>20 划分机构单、DYNAINFO 盘中数据），日K近似移植："
   "机构日=成交额≥阈值(默认5000万)、放量=1.5倍5日均量。",
   "用户提供通达信公式《机构资金拉升选股》（日K近似移植）",
   ("CJE2:=V*C/1e8; "
    "A2:=SUM(IF(CJE2>=N1 AND C>REF(C,1),CJE2,0),0); "
    "A3:=SUM(IF(CJE2>=N1 AND C<REF(C,1),CJE2,0),0); "
    "A4:=SUM(IF(CJE2<N1 AND C>REF(C,1),CJE2,0),0); "
    "A5:=SUM(IF(CJE2<N1 AND C<REF(C,1),CJE2,0),0); "
    "A6:=A2+A3+A4+A5; "
    "JGB:=100*A2/A6; JGJ:=JGB-100*A3/A6; "
    "LS:=JGB-100*A5/A6; "
    "TJ1:=JGJ>N2 AND LS>N2; "
    "JJ1:=SUM(V*C,0)/SUM(V,0); DI:=EMA(JJ1,50)/0.97; "
    "HCS:=COUNT(V>MA(V,5)*N3 AND C>REF(C,1),0); "
    "TJ2:=HCS>REF(HCS,1) AND CROSS(C,DI); "
    "XG:TJ1 AND TJ2;"),
   detail="机构净占比={JGJ:.1f}% 机构买占比={JGB:.1f}%",
   strength="JGJ",
   params=[ParamDef("n1", "机构日成交额阈值", "number", 0.5, 0.05, 10, 0.05, "亿",
                    "单日成交额≥该值记为机构日（原文分笔口径在日K失真，故为近似阈值）"),
           ParamDef("n2", "占比阈值", "number", 18.0, 5, 40, 1, "%",
                    "机构净占比与机构买-散户卖占比需同时超过该值"),
           ParamDef("n3", "放量倍数", "number", 1.5, 1.0, 5, 0.1, "倍",
                    "信号日成交量需达到5日均量的倍数")])

# ============================ 注册 ============================

# 公式型策略共用的扫描参数
SCAN_PARAMS = [
    ParamDef("within_n", "信号有效期", "number", 1, 1, 10, 1, "个交易日",
             "信号出现在最近 N 个交易日内视为命中（1=仅最后一根K线）"),
    ParamDef("board", "选股范围", "select", "全部", description="按板块过滤",
             options=[{"value": "全部", "label": "全部A股"},
                      {"value": "主板", "label": "沪深主板(60/00)"},
                      {"value": "创业板", "label": "创业板(30)"},
                      {"value": "科创板", "label": "科创板(68)"}]),
    ParamDef("exclude_st", "剔除 ST/*ST", "bool", True, description="按股票名称过滤 ST 类"),
    ParamDef("min_amount", "信号日成交额下限", "number", 0, 0, 50, 0.5, "亿",
             "0 = 不过滤；用于排除流动性过差的股票"),
]


def register_all() -> int:
    """把目录中的全部公式注册为 formula 型策略。启动时逐一验证公式语法。"""
    n = 0
    for it in S:
        try:
            engine.compile_formula(it["formula"])
        except Exception as e:  # noqa: BLE001
            log.error("公式 %s(%s) 编译失败: %s", it["name"], it["id"], e)
            raise
        register(StrategyDef(
            id=it["id"], name=it["name"],
            description=f"[{it['cat']}] {it['desc']}",
            source=it["src"], params=SCAN_PARAMS + it["params"],
            kind="formula", category=it["cat"],
            formula=it["formula"], detail_tpl=it["detail"],
            strength=it["strength"],
        ))
        n += 1
    log.info("公式选股策略注册完成：%d 个", n)
    return n
