# 神经 signal 仿真怎么跑（C3 本机，2026-10-22 定稿）

上游 round 19/20 搬进来的 `signal_neural_shadow` / `signal_tracking_shadow` 在车上默认**不启用**
（`/data/signal-color-shadow` 不在，`requested()` 一律为假），所以这套依赖只为「能真跑一遍」存在，
不进生产路径。

## 依赖落在哪

`/data/.pydeps` —— 与 cv2 / shapely / aiohttp 同一个永久依赖目录，`sys.path` 里本来就有它
（`python3 -c "import sys;print(sys.path)"` 可见 `/data/.pydeps`），所以**不需要设 PYTHONPATH**。

| 包 | 版本 | 说明 |
|---|---|---|
| onnx | 1.23.2 | 生成/读替身模型 |
| onnxruntime | 1.31.0 | 跑 detect/classify |
| protobuf | 7.36.2 | onnx 的传递依赖（顶层 `google/`） |
| sympy / packaging / flatbuffers / ml_dtypes / coloredlogs / humanfriendly | 随 onnx 带 | 装的时候用了 `--no-deps`，这些是手工补的 |

2026-10-22 之前它们装在 `/data/tmp/nn_deps`（115 MB，靠 PYTHONPATH 临时挂），已按驾驶者拍板
并入 `/data/.pydeps`，`/data/tmp/nn_deps` 已删除。并入时逐个核对过顶层目录名：与 `.pydeps` 现有包
**零重叠**（`google`、`packaging`、`sympy` 在 `.pydeps` 里原本都没有），因此不会覆盖已有依赖。

## 重装（换机 / 依赖被清后）

```sh
mkdir -p /data/tmp/pipwork            # pip 的 TMPDIR 默认是 150 MB tmpfs，会 No space left
TMPDIR=/data/tmp/pipwork pip install --no-deps --target /data/.pydeps \
  onnx==1.23.2 onnxruntime==1.31.0 protobuf sympy packaging flatbuffers ml_dtypes \
  coloredlogs humanfriendly
rm -rf /data/tmp/pipwork
python3 -c "import onnx, onnxruntime, numpy; print(onnx.__version__, onnxruntime.__version__, numpy.__version__)"
```

注意本机 numpy 是系统自带的 **2.5.1**、cv2 4.13（`--no-deps` + 借用系统包，别再装一份 numpy/cv2）。

## 跑仿真

```sh
cd /data/openpilot
python3 tools/signal_analysis/sim_neural_on_c3.py     # 1.7 s，每阶段一行 JSON
```

替身权重在 `/data/tmp/sub_detector.onnx`、`/data/tmp/sub_classifier.onnx`（各几十 KB），
丢了就重生成：

```sh
python3 tools/signal_analysis/make_substitute_models.py
```

**为什么是替身**：真权重不公开；`make_substitute_models.py` 按 wrapper 期望的
name/shape/rank 输出常量张量。除 sha256 pin（只在仿真里被 patch）外，NV12 裁剪、letterbox 416、
tensor 布局、score 乘积、网格解码、NMS、224 分类裁剪 + ImageNet 归一化、label 查表
全部是真代码 —— 「跑得起来的模型一定是替身」这条约束就是这么落地的。

## 期望输出（2026-10-22 实测）

```
nv12_crop     (760, 1344, 3) uint8；三种坏几何全部 rejected
detect        1 box，score 0.902
classify      red 4.0（原始 logit）；空 crop -> unknown 0.0
sequence_first 1 track，100 ms 后仍在
```

## 相关测试

```sh
python3 -m pytest tools/signal_analysis -q          # 121 passed, 4 skipped
```
