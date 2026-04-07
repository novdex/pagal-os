"""Internationalization (i18n) — multi-language support for PAGAL OS.

Provides a simple translation system for the CLI and web dashboard.
Translations are stored as Python dicts (no external files needed).
The active language is set via PAGAL_LANG environment variable.

Supported languages: en (English), hi (Hindi), es (Spanish), zh (Chinese),
ar (Arabic), fr (French), pt (Portuguese), de (German).
"""

import logging
import os
from typing import Any

logger = logging.getLogger("pagal_os")

# Active language (default: English)
_LANG = os.environ.get("PAGAL_LANG", "en").lower()

# ---------------------------------------------------------------------------
# Translation dictionaries
# ---------------------------------------------------------------------------

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "app_name": "PAGAL OS",
        "dashboard": "Dashboard",
        "my_agents": "My Agents",
        "create_agent": "Create Agent",
        "run": "Run",
        "stop": "Stop",
        "delete": "Delete",
        "settings": "Settings",
        "logs": "Logs",
        "analytics": "Analytics",
        "store": "Store",
        "builder": "Builder",
        "quick_run": "Quick Run",
        "agent_name": "Agent Name",
        "task_placeholder": "Task to perform...",
        "running": "Running...",
        "completed": "Completed",
        "error": "Error",
        "no_agents": "No agents yet. Create one or install from the store.",
        "agent_created": "Agent created successfully!",
        "agent_deleted": "Agent deleted.",
        "settings_saved": "Settings saved!",
        "search": "Search",
        "install": "Install",
        "templates": "Templates",
        "documents": "Documents",
        "upload": "Upload",
        "notifications": "Notifications",
        "budget": "Budget",
        "credits": "Credits",
        "health": "Health",
        "teams": "Teams",
        "hands": "Scheduled Tasks",
        "processes": "Processes",
    },
    "hi": {
        "app_name": "PAGAL OS",
        "dashboard": "डैशबोर्ड",
        "my_agents": "मेरे एजेंट",
        "create_agent": "एजेंट बनाएं",
        "run": "चलाएं",
        "stop": "रोकें",
        "delete": "हटाएं",
        "settings": "सेटिंग्स",
        "logs": "लॉग्स",
        "analytics": "एनालिटिक्स",
        "store": "स्टोर",
        "builder": "बिल्डर",
        "quick_run": "क्विक रन",
        "agent_name": "एजेंट का नाम",
        "task_placeholder": "कार्य दर्ज करें...",
        "running": "चल रहा है...",
        "completed": "पूर्ण",
        "error": "त्रुटि",
        "no_agents": "कोई एजेंट नहीं। एक बनाएं या स्टोर से इंस्टॉल करें।",
        "agent_created": "एजेंट सफलतापूर्वक बनाया गया!",
        "agent_deleted": "एजेंट हटाया गया।",
        "settings_saved": "सेटिंग्स सहेजी गईं!",
        "search": "खोजें",
        "install": "इंस्टॉल",
        "templates": "टेम्पलेट्स",
        "documents": "दस्तावेज़",
        "upload": "अपलोड",
        "notifications": "सूचनाएं",
        "budget": "बजट",
        "credits": "क्रेडिट्स",
        "health": "स्वास्थ्य",
        "teams": "टीमें",
        "hands": "शेड्यूल्ड टास्क",
        "processes": "प्रक्रियाएं",
    },
    "es": {
        "app_name": "PAGAL OS",
        "dashboard": "Panel",
        "my_agents": "Mis Agentes",
        "create_agent": "Crear Agente",
        "run": "Ejecutar",
        "stop": "Detener",
        "delete": "Eliminar",
        "settings": "Configuración",
        "logs": "Registros",
        "analytics": "Analíticas",
        "store": "Tienda",
        "builder": "Constructor",
        "quick_run": "Ejecución Rápida",
        "agent_name": "Nombre del agente",
        "task_placeholder": "Tarea a realizar...",
        "running": "Ejecutando...",
        "completed": "Completado",
        "error": "Error",
        "no_agents": "No hay agentes. Crea uno o instala desde la tienda.",
        "agent_created": "¡Agente creado con éxito!",
        "agent_deleted": "Agente eliminado.",
        "settings_saved": "¡Configuración guardada!",
        "search": "Buscar",
        "install": "Instalar",
        "templates": "Plantillas",
        "documents": "Documentos",
        "upload": "Subir",
        "notifications": "Notificaciones",
        "budget": "Presupuesto",
        "credits": "Créditos",
        "health": "Salud",
        "teams": "Equipos",
        "hands": "Tareas Programadas",
        "processes": "Procesos",
    },
    "zh": {
        "app_name": "PAGAL OS",
        "dashboard": "仪表板",
        "my_agents": "我的代理",
        "create_agent": "创建代理",
        "run": "运行",
        "stop": "停止",
        "delete": "删除",
        "settings": "设置",
        "logs": "日志",
        "analytics": "分析",
        "store": "商店",
        "builder": "构建器",
        "quick_run": "快速运行",
        "agent_name": "代理名称",
        "task_placeholder": "要执行的任务...",
        "running": "运行中...",
        "completed": "已完成",
        "error": "错误",
        "no_agents": "还没有代理。创建一个或从商店安装。",
        "agent_created": "代理创建成功！",
        "agent_deleted": "代理已删除。",
        "settings_saved": "设置已保存！",
        "search": "搜索",
        "install": "安装",
        "templates": "模板",
        "documents": "文档",
        "upload": "上传",
        "notifications": "通知",
        "budget": "预算",
        "credits": "积分",
        "health": "健康",
        "teams": "团队",
        "hands": "定时任务",
        "processes": "进程",
    },
    "fr": {
        "app_name": "PAGAL OS",
        "dashboard": "Tableau de bord",
        "my_agents": "Mes Agents",
        "create_agent": "Créer un Agent",
        "run": "Exécuter",
        "stop": "Arrêter",
        "delete": "Supprimer",
        "settings": "Paramètres",
        "logs": "Journaux",
        "analytics": "Analytique",
        "store": "Boutique",
        "builder": "Constructeur",
        "quick_run": "Exécution Rapide",
        "agent_name": "Nom de l'agent",
        "task_placeholder": "Tâche à effectuer...",
        "running": "En cours...",
        "completed": "Terminé",
        "error": "Erreur",
        "no_agents": "Aucun agent. Créez-en un ou installez depuis la boutique.",
        "agent_created": "Agent créé avec succès !",
        "agent_deleted": "Agent supprimé.",
        "settings_saved": "Paramètres sauvegardés !",
        "search": "Rechercher",
        "install": "Installer",
        "templates": "Modèles",
        "documents": "Documents",
        "upload": "Télécharger",
        "notifications": "Notifications",
        "budget": "Budget",
        "credits": "Crédits",
        "health": "Santé",
        "teams": "Équipes",
        "hands": "Tâches Planifiées",
        "processes": "Processus",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def t(key: str, lang: str | None = None) -> str:
    """Translate a key to the active (or specified) language.

    Falls back to English if the key is not found in the target language.

    Args:
        key: Translation key (e.g. 'dashboard', 'create_agent').
        lang: Override language code (default: uses PAGAL_LANG env).

    Returns:
        Translated string.
    """
    language = lang or _LANG
    translations = _TRANSLATIONS.get(language, _TRANSLATIONS["en"])
    return translations.get(key, _TRANSLATIONS["en"].get(key, key))


def get_language() -> str:
    """Get the current language code."""
    return _LANG


def get_supported_languages() -> list[dict[str, str]]:
    """List all supported languages."""
    names = {
        "en": "English", "hi": "हिन्दी (Hindi)", "es": "Español (Spanish)",
        "zh": "中文 (Chinese)", "fr": "Français (French)",
    }
    return [
        {"code": code, "name": names.get(code, code)}
        for code in sorted(_TRANSLATIONS.keys())
    ]


def get_all_translations(lang: str | None = None) -> dict[str, str]:
    """Get all translations for a language (for passing to templates).

    Args:
        lang: Language code (default: active language).

    Returns:
        Dict of key -> translated string.
    """
    language = lang or _LANG
    # Merge English base with target language
    result = dict(_TRANSLATIONS["en"])
    if language in _TRANSLATIONS:
        result.update(_TRANSLATIONS[language])
    return result
