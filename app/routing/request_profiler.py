from __future__ import annotations

import re
from typing import Any

from app.routing.encoder import SemanticEncoder
from app.routing.schemas import RequestProfile


class RequestProfiler:
    """
    Hybrid request intelligence layer.

    Responsibilities:

        1. Detect input modality:
            - text
            - image
            - document
            - mixed

        2. Detect task intent:
            - general
            - factual
            - analysis
            - reasoning
            - coding
            - creative
            - data

        3. Detect domain:
            - general
            - china_context
            - software_engineering
            - business_market
            - science_math
            - data_analytics
            - finance

        4. Estimate request complexity.

    Important architecture rule:

        This class does NOT select providers.

        It never references:
            - deepseek
            - qwen
            - openai
            - qwen_document

        It only describes the request.

    The router / registry remains responsible for selecting
    the actual model/provider.
    """

    # ============================================================
    # Semantic task prototypes
    # ============================================================

    TASK_PROTOTYPES = {
        "general": (
            "general assistance, everyday questions, broad help, "
            "ordinary conversation and common requests"
        ),
        "factual": (
            "direct factual questions, definitions, concrete facts, "
            "objective information and knowledge lookup"
        ),
        "analysis": (
            "analysis, comparison, evaluation, trends, causes, "
            "consequences, markets, strategy, forecasting and trade-offs"
        ),
        "reasoning": (
            "deep reasoning, deduction, proof, inference, "
            "multi-step problem solving, causal reasoning and logic"
        ),
        "coding": (
            "programming, software development, debugging, source code, "
            "algorithms, databases, APIs, concurrency and architecture"
        ),
        "creative": (
            "creative writing, storytelling, brainstorming, fiction, "
            "advertising, imaginative content and style transformation"
        ),
        "data": (
            "statistics, datasets, data analysis, metrics, calculations, "
            "machine learning and quantitative reasoning"
        ),
    }

    # ============================================================
    # Semantic domain prototypes
    # ============================================================

    DOMAIN_PROTOTYPES = {
        "general": (
            "general knowledge without a strong specialist domain"
        ),
        "china_context": (
            "China-related topics, Chinese society, economy, technology, "
            "business, companies, consumers, markets and policy"
        ),
        "software_engineering": (
            "software engineering, programming, backend systems, "
            "databases, APIs, concurrency, distributed systems and architecture"
        ),
        "business_market": (
            "business, economics, markets, industries, competition, "
            "companies, strategy, products and commercial analysis"
        ),
        "science_math": (
            "mathematics, physics, chemistry, scientific research and "
            "formal quantitative problems"
        ),
        "data_analytics": (
            "data analytics, statistics, datasets, metrics, dashboards "
            "and quantitative interpretation"
        ),
        "finance": (
            "finance, investment, stocks, banking, financial markets "
            "and financial analysis"
        ),
    }

    # ============================================================
    # Explicit task patterns
    # ============================================================

    ANALYSIS_PATTERNS = (
        # Chinese
        r"分析",
        r"比较",
        r"对比",
        r"评估",
        r"评价",
        r"研究",
        r"趋势",
        r"原因",
        r"影响",
        r"后果",
        r"预测",
        r"展望",
        r"战略",
        r"策略",
        r"风险",
        r"优势",
        r"劣势",
        r"收益",
        r"成本",
        r"权衡",
        r"为什么",
        r"怎么看",
        r"有什么区别",
        r"有什么影响",
        r"可行性",
        r"优缺点",
        r"架构流程",
        r"设计方案",
        r"测试方案",
        r"风险分析",

        # English
        r"\bwhy\b",
        r"\banaly[sz]e?\b",
        r"\banalysis\b",
        r"\bevaluate\b",
        r"\bevaluation\b",
        r"\bassess\b",
        r"\bcompare\b",
        r"\bcomparison\b",
        r"\btrend\b",
        r"\boutlook\b",
        r"\bforecast\b",
        r"\bimpact\b",
        r"\bstrategy\b",
        r"\brisk\b",
        r"\bbenefit\b",
        r"\btrade[-\s]?off\b",
        r"\bpros?\b",
        r"\bcons?\b",
    )

    REASONING_PATTERNS = (
        # Chinese
        r"推理",
        r"论证",
        r"证明",
        r"推导",
        r"演绎",
        r"归纳",
        r"推断",
        r"逻辑",
        r"因果",
        r"根因",
        r"根本原因",
        r"为什么",
        r"如何证明",
        r"请证明",
        r"请推导",
        r"逐步",
        r"一步一步",
        r"多步",
        r"解决",
        r"求解",
        r"二叉搜索树",
        r"中序遍历",
        r"算法复杂度",
        r"并发控制",
        r"缓存击穿",
        r"伪代码",

        # English
        r"\bprove\b",
        r"\bproof\b",
        r"\bderive\b",
        r"\bderivation\b",
        r"\bdeduce\b",
        r"\bdeduction\b",
        r"\breason\b",
        r"\breasoning\b",
        r"\blogic\b",
        r"\bcausal\b",
        r"\binfer\b",
        r"\binference\b",
        r"\broot\s+cause\b",
        r"\bstep[-\s]?by[-\s]?step\b",
        r"\bmulti[-\s]?step\b",
        r"\bsolve\b",
    )

    # ============================================================
    # Coding patterns
    # ============================================================

    CODING_PATTERNS = (
        # Languages
        r"\bpython\b",
        r"\bjava\b",
        r"\bkotlin\b",
        r"\brust\b",
        r"\bgolang\b",
        r"\bgo\b",
        r"\bjavascript\b",
        r"\btypescript\b",
        r"\bphp\b",
        r"\bruby\b",
        r"\bc\+\+\b",
        r"\bc#\b",
        r"\bswift\b",

        # Databases / infrastructure
        r"\bsql\b",
        r"\bredis\b",
        r"\bkafka\b",
        r"\brbac\b",
        r"\bmysql\b",
        r"\bpostgresql\b",
        r"\bpostgres\b",
        r"\bmongodb\b",
        r"\bdatabase\b",
        r"\bfastapi\b",
        r"\bspring\s*boot\b",
        r"\bdocker\b",
        r"\bkubernetes\b",
        r"伪代码",
        r"并发控制",
        r"缓存击穿",
        r"异步",

        # APIs / engineering
        r"\bapi\b",
        r"\bsdk\b",
        r"\bdebug\b",
        r"\bdebugging\b",
        r"\bbug\b",
        r"\bexception\b",
        r"\bstack\s*trace\b",
        r"\bevent[-\s]?driven\b",
        r"\bdurability\b",
        r"\bordering\b",
        r"\breplay\b",
        r"\bfailure\s+recovery\b",
        r"\baudit\b",
        r"\btenant\b",
        r"\bmulti[-\s]?tenant\b",
        r"\bthread\b",
        r"\bthreads\b",
        r"\bconcurrency\b",
        r"\basync\b",
        r"\bawait\b",
        r"\bcache\b",
        r"\bretry\b",
        r"\bidempot",
        r"\bfailover\b",
        r"\bdistributed\b",
        r"\bbackend\b",
        r"\bfrontend\b",
        r"\barchitecture\b",
        r"\bsource\s+code\b",
        r"\bcode\b",
        r"\bprogramming\b",
        r"\bsoftware\b",

        # Chinese
        r"代码",
        r"编程",
        r"程序",
        r"开发",
        r"软件",
        r"后端",
        r"前端",
        r"接口",
        r"数据库",
        r"缓存",
        r"调试",
        r"报错",
        r"异常",
        r"线程",
        r"并发",
        r"异步",
        r"架构",
        r"微服务",
        r"分布式",
        r"重试",
        r"故障恢复",
        r"容错",
        r"幂等",
        r"多租户",
        r"权限",
        r"审计",
        r"消息队列",
        r"事件驱动",
    )

    # ============================================================
    # China-context patterns
    # ============================================================

    CHINA_PATTERNS = (
        r"中国",
        r"中国大陆",
        r"大陆",
        r"国内",
        r"人民币",
        r"央行",
        r"国务院",
        r"政策",
        r"监管",
        r"国家统计局",
        r"上海",
        r"北京",
        r"深圳",
        r"广州",
        r"杭州",
        r"香港",
        r"澳门",
        r"腾讯",
        r"阿里巴巴",
        r"阿里",
        r"字节跳动",
        r"百度",
        r"京东",
        r"拼多多",
        r"小米",
        r"华为",
        r"美团",
        r"滴滴",
        r"抖音",
        r"微信",
        r"支付宝",
        r"\bchina\b",
        r"\bchinese\b",
        r"\bmainland\s+china\b",
        r"\brenminbi\b",
        r"\bcny\b",
    )

    # ============================================================
    # Business patterns
    # ============================================================

    BUSINESS_PATTERNS = (
        r"商业",
        r"企业",
        r"公司",
        r"市场",
        r"行业",
        r"竞争",
        r"战略",
        r"策略",
        r"产品",
        r"用户",
        r"客户",
        r"收入",
        r"利润",
        r"成本",
        r"增长",
        r"商业模式",
        r"市场份额",
        r"竞争优势",
        r"供应链",
        r"营销",
        r"销售",
        r"定价",
        r"投资回报",
        r"B2B",
        r"B2C",
        r"PLG",
        r"SaaS",
        r"\bmarket\b",
        r"\bindustry\b",
        r"\bcompetition\b",
        r"\bcompetitive\b",
        r"\bbusiness\b",
        r"\bstrategy\b",
        r"\bproduct\b",
        r"\bpricing\b",
        r"\brevenue\b",
        r"\bprofit\b",
        r"\bcost\b",
        r"\bgrowth\b",
        r"\bforecast\b",
        r"\boutlook\b",
        r"\bCAC\b",
        r"\bretention\b",
        r"\bcash\s+flow\b",
        r"\bPLG\b",
        r"\bB2B\b",
        r"\bB2C\b",
    )

    # ============================================================
    # Software domain patterns
    # ============================================================

    SOFTWARE_PATTERNS = (
        *CODING_PATTERNS,
    )

    # ============================================================
    # Finance patterns
    # ============================================================

    FINANCE_PATTERNS = (
        r"股票",
        r"股价",
        r"投资",
        r"基金",
        r"金融",
        r"银行",
        r"证券",
        r"债券",
        r"期货",
        r"期权",
        r"资产",
        r"负债",
        r"现金流",
        r"估值",
        r"市盈率",
        r"市净率",
        r"利率",
        r"汇率",
        r"财务",
        r"\bstock\b",
        r"\bstocks\b",
        r"\binvestment\b",
        r"\binvest\b",
        r"\bfinance\b",
        r"\bfinancial\b",
        r"\bbanking\b",
        r"\bbond\b",
        r"\bbonds\b",
        r"\bportfolio\b",
        r"\bvaluation\b",
        r"\binterest\s+rate\b",
        r"\bexchange\s+rate\b",
        r"\bP/E\b",
        r"\bEPS\b",
    )

    # ============================================================
    # Data patterns
    # ============================================================

    DATA_PATTERNS = (
        r"数据",
        r"数据分析",
        r"数据集",
        r"统计",
        r"指标",
        r"报表",
        r"仪表盘",
        r"机器学习",
        r"数据科学",
        r"回归",
        r"相关性",
        r"均值",
        r"方差",
        r"概率",
        r"分布",
        r"\bdata\s+analysis\b",
        r"\bdataset\b",
        r"\bstatistics\b",
        r"\bstatistical\b",
        r"\bmetrics\b",
        r"\bdashboard\b",
        r"\bmachine\s+learning\b",
        r"\bdata\s+science\b",
        r"\bregression\b",
        r"\bcorrelation\b",
        r"\bvariance\b",
        r"\bprobability\b",
        r"\bdistribution\b",
    )

    # ============================================================
    # Science / mathematics patterns
    # ============================================================

    SCIENCE_PATTERNS = (
        r"数学",
        r"物理",
        r"化学",
        r"生物",
        r"科学",
        r"微积分",
        r"概率",
        r"统计学",
        r"定理",
        r"证明",
        r"方程",
        r"公式",
        r"\bmath\b",
        r"\bmathematics\b",
        r"\bphysics\b",
        r"\bchemistry\b",
        r"\bbiology\b",
        r"\bcalculus\b",
        r"\btheorem\b",
        r"\bequation\b",
        r"\bformula\b",
    )

    # ============================================================
    # Input / modality patterns
    # ============================================================

    IMAGE_MIME_TYPES = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/svg+xml",
        "image/heic",
        "image/heif",
    }

    DOCUMENT_MIME_TYPES = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/csv",
        "text/plain",
        "application/rtf",
        "text/markdown",
    }

    IMAGE_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
        ".heic",
        ".heif",
    }

    DOCUMENT_EXTENSIONS = {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".csv",
        ".txt",
        ".rtf",
        ".md",
    }

    DOCUMENT_FILENAME_KEYS = (
        "filename",
        "file_name",
        "name",
        "path",
        "uri",
        "url",
    )

    # ============================================================
    # Initialization
    # ============================================================

    def __init__(
        self,
        encoder: SemanticEncoder,
    ) -> None:

        self.encoder = encoder

        self._task_embeddings = {
            name: self.encoder.encode(text)
            for name, text
            in self.TASK_PROTOTYPES.items()
        }

        self._domain_embeddings = {
            name: self.encoder.encode(text)
            for name, text
            in self.DOMAIN_PROTOTYPES.items()
        }

    # ============================================================
    # Generic helpers
    # ============================================================

    @staticmethod
    def _normalize_text(
        value: Any,
    ) -> str:

        if value is None:
            return ""

        return str(value).strip()

    @staticmethod
    def _extension(
        value: str,
    ) -> str:

        value = value.strip().lower()

        if not value:
            return ""

        value = value.split("?", 1)[0]
        value = value.split("#", 1)[0]

        match = re.search(
            r"(\.[a-z0-9]+)$",
            value,
        )

        if not match:
            return ""

        return match.group(1)

    # ============================================================
    # Input modality detection
    # ============================================================

    @classmethod
    def _is_image_item(
        cls,
        item: dict,
    ) -> bool:

        item_type = str(
            item.get(
                "type",
                "",
            )
        ).strip().lower()

        if item_type in {
            "image",
            "image_url",
            "input_image",
            "image_file",
        }:
            return True

        mime_type = str(
            item.get(
                "mime_type",
                item.get(
                    "mimeType",
                    item.get(
                        "content_type",
                        "",
                    ),
                ),
            )
        ).strip().lower()

        if mime_type in cls.IMAGE_MIME_TYPES:
            return True

        if mime_type.startswith("image/"):
            return True

        for key in cls.DOCUMENT_FILENAME_KEYS:

            value = item.get(key)

            if not value:
                continue

            extension = cls._extension(
                str(value)
            )

            if extension in cls.IMAGE_EXTENSIONS:
                return True

        return False

    @classmethod
    def _is_document_item(
        cls,
        item: dict,
    ) -> bool:

        item_type = str(
            item.get(
                "type",
                "",
            )
        ).strip().lower()

        if item_type in {
            "document",
            "document_file",
            "file",
            "input_file",
            "attachment",
        }:
            return True

        mime_type = str(
            item.get(
                "mime_type",
                item.get(
                    "mimeType",
                    item.get(
                        "content_type",
                        "",
                    ),
                ),
            )
        ).strip().lower()

        if mime_type in cls.DOCUMENT_MIME_TYPES:
            return True

        if (
            mime_type.startswith(
                "application/pdf"
            )
        ):
            return True

        for key in cls.DOCUMENT_FILENAME_KEYS:

            value = item.get(key)

            if not value:
                continue

            extension = cls._extension(
                str(value)
            )

            if extension in cls.DOCUMENT_EXTENSIONS:
                return True

        return False

    @classmethod
    def detect_input_type(
        cls,
        messages: list[dict],
    ) -> str:

        """
        Detect the request modality.

        Returns:

            text
                Only textual content exists.

            image
                At least one image exists and no document exists.

            document
                At least one document exists and no image exists.

            mixed
                Multiple modalities are present.

        This method does not choose a provider/model.
        """

        has_text = False
        has_image = False
        has_document = False

        for message in messages:

            if not isinstance(
                message,
                dict,
            ):
                continue

            content = message.get(
                "content",
                "",
            )

            if isinstance(
                content,
                str,
            ):

                if content.strip():
                    has_text = True

                continue

            if not isinstance(
                content,
                list,
            ):
                continue

            for item in content:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                if cls._is_image_item(item):
                    has_image = True
                    continue

                if cls._is_document_item(item):
                    has_document = True
                    continue

                item_type = str(
                    item.get(
                        "type",
                        "",
                    )
                ).strip().lower()

                if item_type in {
                    "text",
                    "input_text",
                }:

                    value = str(
                        item.get(
                            "text",
                            "",
                        )
                    ).strip()

                    if value:
                        has_text = True

        modality_count = sum(
            (
                1 if has_text else 0,
                1 if has_image else 0,
                1 if has_document else 0,
            )
        )

        if modality_count == 0:
            return "text"

        if modality_count > 1:
            return "mixed"

        if has_image:
            return "image"

        if has_document:
            return "document"

        return "text"

    # ============================================================
    # Text extraction
    # ============================================================

    @staticmethod
    def extract_text(
        messages: list[dict],
    ) -> str:

        parts: list[str] = []

        for message in messages:

            if not isinstance(
                message,
                dict,
            ):
                continue

            content = message.get(
                "content",
                "",
            )

            if isinstance(
                content,
                str,
            ):

                value = content.strip()

                if value:
                    parts.append(value)

                continue

            if isinstance(
                content,
                list,
            ):

                for item in content:

                    if not isinstance(
                        item,
                        dict,
                    ):
                        continue

                    item_type = str(
                        item.get(
                            "type",
                            "",
                        )
                    ).strip().lower()

                    if item_type not in {
                        "text",
                        "input_text",
                    }:
                        continue

                    value = str(
                        item.get(
                            "text",
                            "",
                        )
                    ).strip()

                    if value:
                        parts.append(value)

        return "\n".join(parts).strip()

    # ============================================================
    # Pattern signal
    # ============================================================

    @staticmethod
    def _pattern_signal(
        text: str,
        patterns: tuple[str, ...],
        saturation: float,
    ) -> float:

        if not text:
            return 0.0

        hits = 0

        for pattern in patterns:

            try:
                if re.search(
                    pattern,
                    text,
                    re.IGNORECASE,
                ):
                    hits += 1
            except re.error:
                continue

        return max(
            0.0,
            min(
                1.0,
                hits / max(
                    1.0,
                    saturation,
                ),
            ),
        )

    # ============================================================
    # Language
    # ============================================================

    @staticmethod
    def chinese_ratio(
        text: str,
    ) -> float:

        if not text:
            return 0.0

        chinese = len(
            re.findall(
                r"[\u4e00-\u9fff]",
                text,
            )
        )

        latin = len(
            re.findall(
                r"[A-Za-z]",
                text,
            )
        )

        total = chinese + latin

        if total <= 0:
            return 0.0

        return chinese / total

    # ============================================================
    # Code detection
    # ============================================================

    @staticmethod
    def code_ratio(
        text: str,
    ) -> float:

        if not text:
            return 0.0

        blocks = re.findall(
            r"```(?:[A-Za-z0-9_+#.\-]+)?[ \t]*\n?[\s\S]*?```",
            text,
        )

        if not blocks:
            return 0.0

        code_chars = sum(
            len(block)
            for block in blocks
        )

        return max(
            0.0,
            min(
                1.0,
                code_chars
                /
                max(
                    1,
                    len(text),
                ),
            ),
        )

    @staticmethod
    def inline_code_signal(
        text: str,
    ) -> float:

        return RequestProfiler._pattern_signal(
            text,
            (
                r"\bdef\s+\w+",
                r"\bclass\s+\w+",
                r"\bimport\s+\w+",
                r"\bfrom\s+\w+\s+import\b",
                r"\bSELECT\b.+\bFROM\b",
                r"\bINSERT\s+INTO\b",
                r"\bUPDATE\s+\w+\s+SET\b",
                r"\bCREATE\s+TABLE\b",
                r"\basync\s+def\b",
                r"\bawait\s+",
                r"\.\w+\(",
                r"==",
                r"!=",
                r"=>",
                r"->",
            ),
            5.0,
        )

    # ============================================================
    # Semantic scores
    # ============================================================

    def _semantic_scores(
        self,
        prototypes: dict[str, list[float]],
        query_embedding: list[float],
    ) -> dict[str, float]:

        result = {}

        for name, prototype in prototypes.items():

            similarity = self.encoder.cosine(
                query_embedding,
                prototype,
            )

            result[name] = (
                self.encoder.normalize_similarity(
                    similarity
                )
            )

        return result

    @staticmethod
    def _calibrate_independent(
        semantic: dict[str, float],
    ) -> dict[str, float]:

        if not semantic:
            return {}

        values = list(
            semantic.values()
        )

        minimum = min(values)
        maximum = max(values)

        span = max(
            maximum - minimum,
            0.05,
        )

        result = {}

        for name, value in semantic.items():

            relative = (
                value - minimum
            ) / span

            result[name] = (
                0.20
                +
                relative * 0.60
            )

        return result

    # ============================================================
    # Complexity
    # ============================================================

    @staticmethod
    def _complexity(
        text: str,
        task: dict[str, float],
        domain: dict[str, float],
        code_ratio: float,
        inline_code: float,
    ) -> tuple[str, float]:

        coding = task.get(
            "coding",
            0.0,
        )

        reasoning = task.get(
            "reasoning",
            0.0,
        )

        analysis = task.get(
            "analysis",
            0.0,
        )

        data = task.get(
            "data",
            0.0,
        )

        software = domain.get(
            "software_engineering",
            0.0,
        )

        china = domain.get(
            "china_context",
            0.0,
        )

        business = domain.get(
            "business_market",
            0.0,
        )

        objective_patterns = (
            *RequestProfiler.ANALYSIS_PATTERNS,
            "design",
            "explain",
            "performance",
            "complexity",
            "maintainability",
            "architecture",
            "implementation",
            "requirements",
        )

        objective_count = sum(
            1
            for pattern
            in objective_patterns
            if re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
        )

        engineering_patterns = (
            r"\bconcurrency\b",
            r"\bdistributed\b",
            r"\btransaction(?:s|al)?\b",
            r"\b(?:database|postgres(?:ql)?|mysql|sql)\b",
            r"\b(?:lock|locking|deadlock)\b",
            r"\b(?:index|indexing)\b",
            r"\bconnection\s+pool\b",
            r"\brbac\b",
            r"\baudit\b",
            r"\bmulti[-\s]?tenant\b",
            r"\btenant\b",
            r"\bcache\b",
            r"\bretry\b",
            r"\bidempot",
            r"\bfailover\b",
            r"\bkafka\b",
            r"\bevent[-\s]?driven\b",
            r"并发",
            r"事务",
            r"数据库",
            r"锁竞争",
            r"死锁",
            r"索引",
            r"连接池",
            r"分布式",
            r"权限",
            r"审计",
            r"多租户",
            r"缓存",
            r"重试",
            r"幂等",
            r"故障恢复",
            r"事件驱动",
        )

        engineering_count = sum(
            1
            for pattern
            in engineering_patterns
            if re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
        )

        business_depth_patterns = (
            r"\bCAC\b",
            r"\bretention\b",
            r"\bcash\s+flow\b",
            r"\bPLG\b",
            r"\bB2B\b",
            r"\bB2C\b",
            r"\brisk\b",
            r"\bbenefit\b",
            r"市场份额",
            r"竞争优势",
            r"商业模式",
            r"供应链",
            r"用户留存",
            r"现金流",
            r"盈利",
            r"定价",
        )

        business_depth_count = sum(
            1
            for pattern
            in business_depth_patterns
            if re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
        )

        sentence_count = len(
            re.findall(
                r"[.!?。！？]",
                text,
            )
        )

        clause_count = len(
            re.findall(
                r"[,，;；:：]",
                text,
            )
        )

        cognitive = (
            coding * 0.27
            +
            reasoning * 0.30
            +
            analysis * 0.25
            +
            data * 0.10
            +
            software * 0.08
        )

        structure = (
            min(
                1.0,
                code_ratio * 1.5,
            ) * 0.30
            +
            inline_code * 0.08
            +
            min(
                1.0,
                sentence_count / 4.0,
            ) * 0.08
            +
            min(
                1.0,
                clause_count / 8.0,
            ) * 0.08
            +
            min(
                1.0,
                objective_count / 5.0,
            ) * 0.31
            +
            min(
                1.0,
                len(text) / 1200.0,
            ) * 0.15
        )

        if (
            china >= 0.65
            and analysis >= 0.50
            and business >= 0.45
        ):
            structure += 0.08

        if (
            software >= 0.65
            and coding >= 0.60
            and (
                reasoning >= 0.50
                or analysis >= 0.50
            )
        ):
            structure += 0.10

        score = (
            cognitive * 0.64
            +
            structure * 0.36
        )

        if objective_count >= 3:
            score += 0.10

        if engineering_count >= 3:
            score = max(
                score,
                0.70,
            )

        elif engineering_count >= 2:
            score = max(
                score,
                0.58,
            )

        if business_depth_count >= 3:
            score = max(
                score,
                0.46,
            )

        if (
            code_ratio >= 0.10
            and software >= 0.60
            and (
                reasoning >= 0.50
                or analysis >= 0.50
            )
        ):
            score = max(
                score,
                0.72,
            )

        if (
            china >= 0.65
            and analysis >= 0.50
            and business >= 0.45
        ):
            score = max(
                score,
                0.40,
            )

        score = max(
            0.0,
            min(
                1.0,
                score,
            ),
        )

        if score >= 0.66:
            return (
                "complex",
                round(score, 4),
            )

        if score >= 0.38:
            return (
                "medium",
                round(score, 4),
            )

        return (
            "simple",
            round(score, 4),
        )

    # ============================================================
    # Main profiling
    # ============================================================

    def profile(
        self,
        messages: list[dict],
    ) -> RequestProfile:

        if not isinstance(
            messages,
            list,
        ):
            raise ValueError(
                "messages must be list"
            )

        if not messages:
            raise ValueError(
                "messages empty"
            )

        input_type = (
            self.detect_input_type(
                messages
            )
        )

        text = self.extract_text(
            messages
        )

        # Image/document-only requests may have no textual content.
        # Keep a minimal semantic query so the existing embedding
        # pipeline remains stable.
        semantic_text = text

        if not semantic_text:

            if input_type == "image":
                semantic_text = (
                    "image input requiring visual understanding"
                )

            elif input_type == "document":
                semantic_text = (
                    "document input requiring document understanding"
                )

            elif input_type == "mixed":
                semantic_text = (
                    "mixed text image or document request"
                )

            else:
                raise ValueError(
                    "request contains no text"
                )

        query_embedding = self.encoder.encode(
            semantic_text
        )

        chinese = self.chinese_ratio(
            text
        )

        language = (
            "zh"
            if chinese >= 0.30
            else "en"
        )

        raw_task = self._semantic_scores(
            self._task_embeddings,
            query_embedding,
        )

        raw_domain = self._semantic_scores(
            self._domain_embeddings,
            query_embedding,
        )

        task = self._calibrate_independent(
            raw_task
        )

        domain = self._calibrate_independent(
            raw_domain
        )

        code_ratio = self.code_ratio(
            text
        )

        inline_code = self.inline_code_signal(
            text
        )

        coding_signal = max(
            self._pattern_signal(
                text,
                self.CODING_PATTERNS,
                6.0,
            ),
            inline_code,
            code_ratio,
        )

        analysis_signal = (
            self._pattern_signal(
                text,
                self.ANALYSIS_PATTERNS,
                6.0,
            )
        )

        reasoning_signal = (
            self._pattern_signal(
                text,
                self.REASONING_PATTERNS,
                5.0,
            )
        )

        china_signal = (
            self._pattern_signal(
                text,
                self.CHINA_PATTERNS,
                4.0,
            )
        )

        business_signal = (
            self._pattern_signal(
                text,
                self.BUSINESS_PATTERNS,
                5.0,
            )
        )

        software_signal = (
            self._pattern_signal(
                text,
                self.SOFTWARE_PATTERNS,
                6.0,
            )
        )

        finance_signal = (
            self._pattern_signal(
                text,
                self.FINANCE_PATTERNS,
                5.0,
            )
        )

        data_signal = (
            self._pattern_signal(
                text,
                self.DATA_PATTERNS,
                5.0,
            )
        )

        science_signal = (
            self._pattern_signal(
                text,
                self.SCIENCE_PATTERNS,
                5.0,
            )
        )

        # ========================================================
        # Semantic + explicit task fusion
        # ========================================================

        task["coding"] = min(
            1.0,
            task.get(
                "coding",
                0.20,
            ) * 0.55
            +
            coding_signal * 0.45,
        )

        task["analysis"] = min(
            1.0,
            task.get(
                "analysis",
                0.20,
            ) * 0.55
            +
            analysis_signal * 0.45,
        )

        task["reasoning"] = min(
            1.0,
            task.get(
                "reasoning",
                0.20,
            ) * 0.60
            +
            reasoning_signal * 0.40,
        )

        task["data"] = min(
            1.0,
            task.get(
                "data",
                0.20,
            ) * 0.65
            +
            data_signal * 0.35,
        )

        # ========================================================
        # Strong engineering evidence
        # ========================================================

        explicit_engineering = (
            coding_signal >= 0.50
            or software_signal >= 0.55
            or code_ratio >= 0.10
        )

        if explicit_engineering:

            task["coding"] = max(
                task["coding"],
                0.78,
            )

            domain[
                "software_engineering"
            ] = max(
                domain.get(
                    "software_engineering",
                    0.20,
                ),
                0.72,
            )

        # ========================================================
        # Strong reasoning evidence
        # ========================================================

        if reasoning_signal >= 0.50:

            task["reasoning"] = max(
                task["reasoning"],
                0.72,
            )

        # ========================================================
        # Strong China evidence
        # ========================================================

        if china_signal >= 0.50:

            domain[
                "china_context"
            ] = max(
                domain.get(
                    "china_context",
                    0.20,
                ),
                0.70,
            )

        # ========================================================
        # Business evidence
        # ========================================================

        if business_signal >= 0.50:

            domain[
                "business_market"
            ] = max(
                domain.get(
                    "business_market",
                    0.20,
                ),
                0.70,
            )

            task["analysis"] = max(
                task["analysis"],
                0.68,
            )

        # ========================================================
        # Finance evidence
        # ========================================================

        if finance_signal >= 0.50:

            domain[
                "finance"
            ] = max(
                domain.get(
                    "finance",
                    0.20,
                ),
                0.72,
            )

            task["analysis"] = max(
                task["analysis"],
                0.65,
            )

        # ========================================================
        # Data evidence
        # ========================================================

        if data_signal >= 0.50:

            domain[
                "data_analytics"
            ] = max(
                domain.get(
                    "data_analytics",
                    0.20,
                ),
                0.72,
            )

            task["data"] = max(
                task["data"],
                0.72,
            )

        # ========================================================
        # Science/math evidence
        # ========================================================

        if science_signal >= 0.50:

            domain[
                "science_math"
            ] = max(
                domain.get(
                    "science_math",
                    0.20,
                ),
                0.72,
            )

            task["reasoning"] = max(
                task["reasoning"],
                0.60,
            )

        # ========================================================
        # Analytical China/business request
        # ========================================================

        if (
            china_signal >= 0.40
            and business_signal >= 0.40
            and analysis_signal >= 0.35
        ):

            task["analysis"] = max(
                task["analysis"],
                0.72,
            )

            domain[
                "china_context"
            ] = max(
                domain.get(
                    "china_context",
                    0.20,
                ),
                0.70,
            )

            domain[
                "business_market"
            ] = max(
                domain.get(
                    "business_market",
                    0.20,
                ),
                0.65,
            )

        # ========================================================
        # Coding false-positive suppression
        # ========================================================

        if (
            coding_signal < 0.15
            and software_signal < 0.15
            and code_ratio <= 0.0
        ):

            task["coding"] = min(
                task["coding"],
                0.18,
            )

        # ========================================================
        # Image/document requests should not accidentally become
        # coding requests merely because their textual instruction
        # contains generic technical words.
        #
        # We still preserve explicit code blocks when present.
        # ========================================================

        if input_type in {
            "image",
            "document",
        } and code_ratio <= 0.01:

            if coding_signal < 0.50:
                task["coding"] = min(
                    task.get(
                        "coding",
                        0.20,
                    ),
                    0.40,
                )

        # ========================================================
        # Labels
        # ========================================================

        task_label = max(
            task,
            key=task.get,
        )

        domain_label = max(
            domain,
            key=domain.get,
        )

        # ========================================================
        # Semantic confidence
        # ========================================================

        task_confidence = (
            self._classification_confidence(
                task
            )
        )

        domain_confidence = (
            self._classification_confidence(
                domain
            )
        )

        complexity, complexity_score = (
            self._complexity(
                text,
                task,
                domain,
                code_ratio,
                inline_code,
            )
        )

        # ========================================================
        # Token estimation
        # ========================================================

        if language == "zh":

            estimated_tokens = max(
                1,
                int(
                    len(text) * 1.05
                ),
            )

        else:

            estimated_tokens = max(
                1,
                int(
                    len(text) / 4.0
                ),
            )

        # ========================================================
        # Build existing RequestProfile
        # ========================================================

        profile = RequestProfile(
            text=text,
            language=language,
            chinese_ratio=round(
                chinese,
                4,
            ),
            task=task_label,
            task_confidence=round(
                task_confidence,
                4,
            ),
            domain=domain_label,
            domain_confidence=round(
                domain_confidence,
                4,
            ),
            complexity=complexity,
            complexity_score=round(
                complexity_score,
                4,
            ),
            coding_score=round(
                task.get(
                    "coding",
                    0.0,
                ),
                4,
            ),
            reasoning_score=round(
                task.get(
                    "reasoning",
                    0.0,
                ),
                4,
            ),
            analysis_score=round(
                task.get(
                    "analysis",
                    0.0,
                ),
                4,
            ),
            factual_score=round(
                task.get(
                    "factual",
                    0.0,
                ),
                4,
            ),
            creative_score=round(
                task.get(
                    "creative",
                    0.0,
                ),
                4,
            ),
            data_score=round(
                task.get(
                    "data",
                    0.0,
                ),
                4,
            ),
            estimated_input_tokens=
                estimated_tokens,
            message_count=
                len(messages),
            text_length=
                len(text),
            code_ratio=round(
                code_ratio,
                4,
            ),
        )

        # ========================================================
        # Compatibility metadata
        #
        # Do not require schemas.py to be changed yet.
        #
        # The router can access:
        #
        #     profile.input_type
        #
        # after this profiler runs.
        # ========================================================

        try:

            setattr(
                profile,
                "input_type",
                input_type,
            )

        except Exception:
            pass

        try:

            setattr(
                profile,
                "has_image",
                input_type in {
                    "image",
                    "mixed",
                },
            )

        except Exception:
            pass

        try:

            setattr(
                profile,
                "has_document",
                input_type in {
                    "document",
                    "mixed",
                },
            )

        except Exception:
            pass

        return profile

    # ============================================================
    # Classification confidence
    # ============================================================

    @staticmethod
    def _classification_confidence(
        scores: dict[str, float],
    ) -> float:

        values = sorted(
            scores.values(),
            reverse=True,
        )

        if len(values) < 2:
            return 1.0

        margin = max(
            0.0,
            values[0] - values[1],
        )

        return max(
            0.0,
            min(
                1.0,
                0.50
                +
                margin * 2.5,
            ),
        )


__all__ = [
    "RequestProfiler",
]
