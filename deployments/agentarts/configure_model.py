"""Store optional preview model configuration in ignored runtime, never in source."""
import getpass
import json
from pathlib import Path
from urllib.parse import urlparse


def main():
    root = Path(__file__).resolve().parents[2]
    print('仅保存本项目预览配置；不会调用模型、修改本地工作台环境或创建云资源。')
    endpoint = input('完整 Chat Completions HTTPS 地址：').strip()
    url = urlparse(endpoint)
    if url.scheme != 'https' or not url.netloc or url.query or url.fragment or url.username: raise ValueError('地址必须为无查询参数和凭据的HTTPS接口')
    model = input('控制台显示的模型名称：').strip()
    proxy = input('通过模型代理的自定义鉴权头？y/N：').strip().lower() == 'y'
    header = input('API Key请求头名称：').strip() if proxy else 'Authorization'
    key = getpass.getpass('模型API Key（不回显）：').strip()
    if not model or not key or not header: raise ValueError('模型、鉴权头和密钥不能为空')
    path = root / 'runtime/agentarts-local-config.json'; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'CLOUD_MODEL_ENDPOINT': endpoint, 'CLOUD_MODEL_NAME': model, 'CLOUD_MODEL_API_KEY': key,
                               'CLOUD_MODEL_AUTH_HEADER': header, 'CLOUD_MODEL_AUTH_PREFIX': '' if proxy else 'Bearer',
                               'CLOUD_MODEL_JSON_MODE': '1'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('配置已保存到本项目runtime目录（含密钥，请勿分享或上传）：' + str(path))


if __name__ == '__main__': main()
