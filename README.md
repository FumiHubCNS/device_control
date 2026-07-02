# device-control

HV電源やオシロスコープなど、ttyUSB/SCPI/VISA/Ethernetで操作する実験機器の統合ライブラリです。

## Layout

- `src/device_control/protocol`: シリアル、SCPI、IEEE 488.2 blockなどの共通通信ヘルパ
- `src/device_control/webui`: WebUI共通テンプレート
- `src/device_control/kikusui`: KIKUSUI KX-S系HV電源のttyUSB制御とWebUI
- `src/device_control/mho98`: RIGOL/MHO98系オシロスコープのMinimum triggered DAQ、HDF5保存、CLI、WebUI

## Commands

KIKUSUI HV WebUI:

```bash
uv run device-control-kikusui-web --host 0.0.0.0 --port 8081
```

オシロスコープの従来CLI相当:

```bash
uv run device-control-scope-daq -ip 172.16.206.60 -n 10 -of scope_data.h5 -ch 1 2 3 4
```

オシロスコープWebUI:

```bash
uv run device-control-scope-web --ip 172.16.206.60 --host 0.0.0.0 --port 8082
```

PyQtGraphのライブビュアーも使う場合:

```bash
uv sync --extra viewer
```
