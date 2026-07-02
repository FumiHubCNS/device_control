# device-control

HV電源やオシロスコープなど、ttyUSB/SCPI/VISA/Ethernetで操作する実験機器の統合ライブラリです。

## Layout

- `src/device_control/protocol`: シリアル、SCPI、IEEE 488.2 blockなどの共通通信ヘルパ
- `src/device_control/webui`: WebUI共通テンプレート
- `src/device_control/kikusui`: KIKUSUI KX-S系HV電源のttyUSB制御とWebUI
- `src/device_control/mho98`: RIGOL/MHO98系オシロスコープのMinimum triggered DAQ、HDF5保存、CLI、WebUI
- `src/device_control/tektronix/afg1062`: Tektronix AFG1062 Function GeneratorのCLI/WebUI
- `src/device_control/tektronix/mdo3034`: Tektronix MDO3034オシロスコープの設定確認、WebUI波形取得、CSV保存

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

Tektronix AFG1062の現状確認:

```bash
uv run device-control-afg1062 --resource 'USB0::0x0699::...::INSTR' status
```

Tektronix AFG1062のチャンネル設定:

```bash
uv run device-control-afg1062 --resource 'USB0::0x0699::...::INSTR' set -ch 1 \
  --waveform SIN --frequency 1000 --amplitude 1.0 --offset 0 --output on
```

Tektronix AFG1062 WebUI:

```bash
uv run device-control-afg1062-web --resource 'USB0::0x0699::...::INSTR' --host 0.0.0.0 --port 8083
```

Tektronix MDO3034 WebUI:

```bash
uv run device-control-mdo3034-web --ip 172.16.206.60 --host 0.0.0.0 --port 8084
```

MDO3034をsocket server経由で使う場合は、WebUIのSocketチェックをONにするか、VISA resourceに
`TCPIP0::<ip>::4000::SOCKET` を指定します。

PyQtGraphのライブビュアーも使う場合:

```bash
uv sync --extra viewer
```
