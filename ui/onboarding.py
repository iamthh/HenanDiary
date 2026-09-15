"""首次使用引导（需求 F5）：两屏——隐私告知确认 → 填 Key 并当场测连通。

引导结束前不开始采集：main.py 以 settings["onboarding"]["done"] 门控。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWizard, QWizardPage,
)

import config
from ai.client import AIClient, encrypt_key
from logger import get_logger

log = get_logger(__name__)

_PRIVACY_TEXT = """<b>这个应用做什么</b>
<ul>
<li>工作时间内每隔几分钟给整个屏幕拍一张照，交给 AI 转成一句文字描述。</li>
<li>截图<b>绝不写入硬盘</b>，分析完即销毁；保存的只有文字描述（保留 3 天）。</li>
<li>每晚自动生成一份日报，数据只存在本机（%APPDATA%\\HenanDiary）。</li>
<li>截图内容会经过你自己配置的 AI 服务商，请确认接受后再继续。</li>
</ul>
说明：因 Windows 虚拟内存机制，内存不足时内存页可能被换入 pagefile.sys，本应用无法杜绝。"""


class _IntroPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("它采什么、存哪里")
        label = QLabel(_PRIVACY_TEXT)
        label.setWordWrap(True)
        QVBoxLayout(self).addWidget(label)


class _KeyPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("配置 AI Key")

        ai = config.load_settings()["ai"]
        self._url = QLineEdit(ai["base_url"])
        self._model = QLineEdit(ai["model"])
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._key.setPlaceholderText("留空=保留已配置的 Key")

        form = QFormLayout()
        form.addRow("Base URL", self._url)
        form.addRow("模型名", self._model)
        form.addRow("API Key", self._key)
        test = QLabel("点 Finish 会当场测一次连通性；测不通不会结束引导，"
                      "下次启动还会进来，也可稍后在设置里改。")
        test.setWordWrap(True)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(test)

    def validatePage(self) -> bool:  # QWizard 在 Finish 时调用，通过才结束引导
        key = self._key.text().strip()
        if key:
            config.update_settings({
                "ai": {
                    "api_key_encrypted": encrypt_key(key),
                    "base_url": self._url.text().strip(),
                    "model": self._model.text().strip(),
                },
            })
        else:  # 留空 = 用已配好的 Key（如开发者此前用命令行配过）
            config.update_settings({
                "ai": {"base_url": self._url.text().strip(),
                       "model": self._model.text().strip()},
            })
            if not config.load_settings()["ai"]["api_key_encrypted"]:
                QMessageBox.warning(self, "缺少 Key", "请填写 API Key")
                return False
        try:
            AIClient().test_connection()
        except Exception as e:
            log.exception("引导测连通失败")
            QMessageBox.warning(self, "测试失败", f"接口不可用：{e}")
            return False
        config.update_settings({"onboarding": {"done": True}})
        log.info("首次引导完成，开始采集")
        return True

    def nextId(self) -> int:
        """Key 页就是最后一页，返回 -1 告诉 QWizard「没有下一页」。

        必须是 -1：返回 None 不会报错，但向导会**既不前进也不结束**——按钮显示成 Next，
        点下去毫无反应。2026-09-15 实际踩到：日志里 validatePage 连着成功 14 次、
        settings 也落盘了，人却卡在向导里出不来。
        """
        return -1


class OnboardingWizard(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("欢迎使用 HenanDiary")
        self.addPage(_IntroPage())
        self.addPage(_KeyPage())
