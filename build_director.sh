BASE_DIR="$(dirname "$0")"

# 进入到 celery-director 文件夹
cd "$BASE_DIR" || exit 1
# 删除 algo-server/ 目录下的原来所有 .whl 文件
rm -f ../*.whl
echo "已删除原来的 wheel"

# 运行打包命令
python setup.py bdist_wheel

# 找到最新的 wheel 文件
WHEEL_FILE=$(ls -t dist/*.whl | head -n 1)

# 确保 wheel 文件存在
if [ -z "$WHEEL_FILE" ]; then
    echo "打包失败，未找到 .whl 文件"
    exit 1
fi

# 复制 wheel 文件到 algo 目录
cp "$WHEEL_FILE" ../
echo "已复制 $(basename "$WHEEL_FILE") 到 algo-server/"
rm -rf build
