/**
 * 初中数学智能教学系统 - 主应用
 * 单页应用(SPA)架构
 */

// ==================== 配置 ====================
const API_BASE = 'http://localhost:8000';

// 获取 APP 元素的辅助函数
function getAPP() {
    const app = document.getElementById('app');
    if (!app) {
        console.error('[ERROR] APP element not found!');
    }
    return app;
};

// ==================== 状态管理 ====================
const state = {
    sessionId: localStorage.getItem('sessionId') || null,
    currentUser: null,
    currentPage: 'login'
};

// ==================== 路由配置 ====================
const routes = {
    '/login': '/student/frontend/pages/login.html',
    '/student': '/student/frontend/pages/student.html',
    '/student/catalog': '/student/frontend/pages/course_catalog.html',
    '/student/learning': '/student/frontend/pages/course_learning.html'
};

// ==================== 工具函数 ====================
/**
 * HTML转义函数 - 转义HTML特殊字符，但保留LaTeX公式
 * @param {string} text - 需要转义的文本
 * @returns {string} - 转义后的HTML安全文本
 */
function escapeHtml(text) {
    if (typeof text !== 'string') return '';

    // 先保护LaTeX公式（支持所有 MathJax 识别的数学定界符）
    const latexBlocks = [];
    const mathRegex = /\$\$[\s\S]*?\$\$|\\\[.*?\\\]|\\$$.*?\\$$|\$[^\$\n]+?\$|\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}/g;
    let protectedText = text.replace(mathRegex, (match) => {
        latexBlocks.push(match);
        return `%%LATEX_${latexBlocks.length - 1}%%`;
    });

    // 转义HTML特殊字符
    const div = document.createElement('div');
    div.textContent = protectedText;
    let result = div.innerHTML;

    // 恢复LaTeX公式
    result = result.replace(/%%LATEX_(\d+)%%/g, (_, idx) => latexBlocks[parseInt(idx)]);

    return result;
}

/**
 * 转义HTML属性值
 * @param {string} text - 需要转义的文本
 * @returns {string} - 转义后的安全属性值
 */
function escapeHtmlAttr(text) {
    if (typeof text !== 'string') return '';
    return text
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ==================== API 请求 ====================
// 友好错误消息映射
const ERROR_MESSAGES = {
    // 网络错误
    'Failed to fetch': '网络连接失败，请检查网络连接',
    'Failed to load resource': '加载失败，请检查网络连接',
    'NetworkError': '网络错误，请检查网络连接',

    // HTTP 状态码
    '400': '请求参数错误，请检查输入内容',
    '401': '登录已过期，请重新登录',
    '403': '没有权限执行此操作',
    '404': '请求的资源不存在',
    '409': '数据冲突，请刷新页面后重试',
    '422': '请求数据格式错误，请检查输入',
    '429': '请求过于频繁，请稍后再试',
    '500': '服务器内部错误，请稍后重试',
    '502': '服务器暂时不可用，请稍后重试',
    '503': '服务维护中，请稍后访问',
    '504': '服务器响应超时，请稍后重试',

    // 业务错误
    'Invalid credentials': '用户名或密码错误',
    'Session not found': '会话已过期，请重新登录',
    'Session expired': '会话已过期，请重新登录',
    'Course not found': '课程不存在',
    'Chapter not found': '章节不存在',
    'Invalid request': '请求格式错误',
    'Permission denied': '权限不足',
    'Resource not found': '资源不存在'
};

/**
 * 获取友好的错误消息
 */
function getFriendlyErrorMessage(error) {
    let errorMessage = '';

    if (typeof error === 'string') {
        errorMessage = error;
    } else if (error && error.message) {
        errorMessage = error.message;
    } else if (error && error.detail) {
        errorMessage = error.detail;
    } else {
        errorMessage = String(error);
    }

    // 检查是否有匹配的错误消息
    for (const [key, value] of Object.entries(ERROR_MESSAGES)) {
        if (errorMessage.includes(key)) {
            return value;
        }
    }

    // 如果没有匹配的，返回原始消息（如果已经是中文）或默认消息
    if (/[\u4e00-\u9fa5]/.test(errorMessage)) {
        return errorMessage;
    }

    return '操作失败，请稍后重试';
}

async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };

    if (state.sessionId) {
        url += (url.includes('?') ? '&' : '?') + `session_id=${state.sessionId}`;
    }

    const response = await fetch(API_BASE + url, {
        ...defaultOptions,
        ...options,
    });

    if (!response.ok) {
        let errorData;
        try {
            errorData = await response.json();
        } catch {
            errorData = { detail: `HTTP ${response.status}` };
        }
        throw new Error(getFriendlyErrorMessage(errorData));
    }

    return response.json();
}

// ==================== 消息提示 ====================
/**
 * 显示提示消息（支持操作按钮）
 */
function showToast(message, type = 'info', options = {}) {
    const { duration = 3000, actions = [] } = options;

    // 移除已有的 toast
    const existingToasts = document.querySelectorAll('.toast');
    existingToasts.forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    // 消息内容容器
    const contentContainer = document.createElement('div');
    contentContainer.className = 'toast-content';
    contentContainer.textContent = message;
    toast.appendChild(contentContainer);

    // 添加操作按钮
    if (actions.length > 0) {
        const actionsContainer = document.createElement('div');
        actionsContainer.className = 'toast-actions';

        actions.forEach(action => {
            const button = document.createElement('button');
            button.className = `toast-action ${action.primary ? 'toast-action-primary' : ''}`;
            button.textContent = action.text;
            button.onclick = () => {
                if (action.onClick) {
                    action.onClick();
                }
                toast.remove();
            };
            actionsContainer.appendChild(button);
        });

        toast.appendChild(actionsContainer);
    }

    document.body.appendChild(toast);

    // 自动隐藏（如果有操作按钮，延长显示时间）
    if (actions.length === 0) {
        setTimeout(() => toast.remove(), duration);
    } else {
        setTimeout(() => {
            if (toast.parentElement) {
                toast.classList.add('toast-fading');
                setTimeout(() => toast.remove(), 300);
            }
        }, Math.max(duration, 5000));
    }
}

// ==================== 页面加载器 ====================
// HTML缓存版本号（每次修改HTML后递增）
const HTML_VERSION = 'v17';

async function loadPage(pageName) {
    try {
        // 添加版本号绕过浏览器缓存
        const url = pageName.includes('?') ? `${pageName}&${HTML_VERSION}` : `${pageName}?${HTML_VERSION}`;
        const response = await fetch(url);
        const html = await response.text();


        // 先设置 HTML
        const APP = getAPP();
        if (!APP) return;
        APP.innerHTML = html;

        // 手动执行页面中的 script 标签
        const scripts = APP.querySelectorAll('script');
        scripts.forEach(script => {
            const newScript = document.createElement('script');
            if (script.src) {
                newScript.src = script.src;
            } else {
                newScript.textContent = script.textContent;
            }
            // 复制所有属性
            Array.from(script.attributes).forEach(attr => {
                if (attr.name !== 'src' && attr.name !== 'type') {
                    newScript.setAttribute(attr.name, attr.value);
                }
            });
            script.parentNode.replaceChild(newScript, script);
        });

        initPageScripts(pageName);
    } catch (error) {
        console.error('页面加载失败:', error);
        const errorApp = getAPP();
        if (errorApp) {
            errorApp.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
        }
    }
}

function initPageScripts(pageName) {
    if (pageName.includes('login.html')) {
        initLoginPage();
    } else if (pageName.includes('student.html')) {
        initStudentPage();
    } else if (pageName.includes('teacher.html')) {
        initTeacherPage();
    } else if (pageName.includes('course_catalog.html')) {
        // 课程目录页面有内联脚本，无需额外初始化
    } else if (pageName.includes('course_learning.html')) {
        // 课程学习页面有内联脚本，无需额外初始化
    }
}

// ==================== 路由导航 ====================
function navigate(route) {
    if (!routes[route]) {
        console.error('路由不存在:', route);
        return;
    }

    state.currentPage = route;
    loadPage(routes[route]);
}

// ==================== 检查登录状态 ====================
async function checkAuth() {
    if (!state.sessionId) {
        // 跳转到根路径的统一登录页面
        window.location.href = '/';
        return;
    }

    try {
        const response = await apiRequest('/api/auth/me');
        state.currentUser = response.user;

        // 根据角色跳转
        if (state.currentUser.role === 'teacher') {
            navigate('/teacher');
        } else {
            navigate('/student');
        }
    } catch (error) {
        // 会话无效，返回登录页
        state.sessionId = null;
        state.currentUser = null;
        localStorage.removeItem('sessionId');
        // 跳转到根路径的统一登录页面
        window.location.href = '/';
    }
}

// ==================== 登出 ====================
function logout() {
    apiRequest('/api/auth/logout').finally(() => {
        state.sessionId = null;
        state.currentUser = null;
        localStorage.removeItem('sessionId');
        // 跳转到根路径的统一登录页面
        window.location.href = '/';
    });
}

// ==================== 全局函数（登录页使用） ====================
// 这些函数需要在页面加载前就可用

window.openModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
        modal.style.display = 'flex';
    }
};

window.closeModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        modal.style.display = 'none';
    }
};

window.switchModal = function(currentModal, targetModal) {
    closeModal(currentModal);
    setTimeout(() => openModal(targetModal), 100);
};

window.scrollToSection = function(event, sectionId) {
    event.preventDefault();
    const section = document.getElementById(sectionId);
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
};

// ==================== 登录页逻辑 ====================
function initLoginPage() {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    // 定义模态框操作函数
    const openModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('show');
            modal.style.display = 'flex';
        }
    };

    const closeModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('show');
            modal.style.display = 'none';
        }
    };

    const switchModal = function(currentModal, targetModal) {
        closeModal(currentModal);
        setTimeout(() => openModal(targetModal), 100);
    };

    const scrollToSection = function(event, sectionId) {
        if (event) event.preventDefault();
        const section = document.getElementById(sectionId);
        if (section) {
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    };

    // 绑定模态框打开按钮
    const modalButtons = document.querySelectorAll('[data-modal]');
    modalButtons.forEach((btn, index) => {
        btn.addEventListener('click', (e) => {
            const modalId = btn.getAttribute('data-modal');
            openModal(modalId);
        });
    });

    // 绑定关闭按钮
    const closeButtons = document.querySelectorAll('[data-close]');
    closeButtons.forEach((btn, index) => {
        btn.addEventListener('click', (e) => {
            const modalId = btn.getAttribute('data-close');
            closeModal(modalId);
        });
    });

    // 绑定滚动链接
    const scrollLinks = document.querySelectorAll('[data-scroll]');
    scrollLinks.forEach((link) => {
        link.addEventListener('click', (e) => {
            const sectionId = link.getAttribute('data-scroll');
            scrollToSection(e, sectionId);
        });
    });

    // 绑定切换模态框链接
    const switchLinks = document.querySelectorAll('[data-switch]');
    switchLinks.forEach((link) => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targets = link.getAttribute('data-switch').split(',');
            switchModal(targets[0], targets[1]);
        });
    });

    // 点击模态框背景关闭
    setTimeout(() => {
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    closeModal(modal.id);
                }
            });
        });
    }, 100);

    // 登录表单
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;

            try {
                const response = await apiRequest('/api/auth/login', {
                    method: 'POST',
                    body: JSON.stringify({ username, password })
                });

                state.sessionId = response.session_id;
                state.currentUser = response.user;
                localStorage.setItem('sessionId', response.session_id);

                closeModal('loginModal');
                showToast('登录成功！', 'success');
                setTimeout(() => {
                    // 登录成功后跳转到对应的完整页面
                    if (response.user.role === 'teacher') {
                        window.location.href = '/teacher/frontend/index.html';
                    } else {
                        window.location.href = '/student/frontend/index.html';
                    }
                }, 500);
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    }

    // 注册表单
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const role = document.getElementById('registerRole').value;
            const username = document.getElementById('registerUsername').value.trim();
            const password = document.getElementById('registerPassword').value;
            const email = document.getElementById('registerEmail').value.trim();

            // 客户端验证
            if (username.length < 2 || username.length > 20) {
                showToast('用户名长度必须在2-20个字符之间', 'error');
                return;
            }

            if (password.length < 6) {
                showToast('密码长度至少为6位', 'error');
                return;
            }

            const data = {
                username: username,
                password: password,
                role: role,
                email: email
            };

            if (role === 'student') {
                const studentId = document.getElementById('registerStudentId').value.trim();
                const className = document.getElementById('registerClass').value.trim();

                if (!studentId) {
                    showToast('请输入学号', 'error');
                    return;
                }
                if (!className) {
                    showToast('请输入班级', 'error');
                    return;
                }

                data.student_id = studentId;
                data.class_name = className;
            }

            try {
                // 禁用提交按钮，防止重复提交
                const submitBtn = registerForm.querySelector('button[type="submit"]');
                const originalText = submitBtn.textContent;
                submitBtn.disabled = true;
                submitBtn.textContent = '注册中...';

                const response = await apiRequest('/api/auth/register', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });

                showToast('注册成功！请登录', 'success');
                closeModal('registerModal');
                openModal('loginModal');
                registerForm.reset();
            } catch (error) {
                showToast(error.message || '注册失败，请稍后重试', 'error');
            } finally {
                // 恢复提交按钮
                const submitBtn = registerForm.querySelector('button[type="submit"]');
                submitBtn.disabled = false;
                submitBtn.textContent = '注册';
            }
        });

        // 角色切换时显示/隐藏学生字段
        const roleSelect = document.getElementById('registerRole');
        const studentFields = document.getElementById('studentFields');

        if (roleSelect && studentFields) {
            // 初始化状态
            studentFields.style.display = roleSelect.value === 'student' ? 'block' : 'none';

            roleSelect.addEventListener('change', () => {
                studentFields.style.display = roleSelect.value === 'student' ? 'block' : 'none';
            });
        }
    }
}

// ==================== 学生端逻辑 ====================
function initStudentPage() {
    // 设置用户信息
    const userInfo = document.querySelector('.user-name');
    if (userInfo && state.currentUser) {
        userInfo.textContent = state.currentUser.username;
    }

    // 加载课程
    loadStudentCourses();

    // 导航事件
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            const target = item.dataset.target;
            document.querySelectorAll('.content-page').forEach(p => p.classList.remove('active'));
            document.getElementById(target).classList.add('active');

            // 加载对应内容
            if (target === 'courses') loadStudentCourses();
            else if (target === 'join-class') loadJoinClassPage();
            else if (target === 'ai-tutor') initAITutor();
        });
    });

    // 登出按钮
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
}

async function loadStudentCourses() {
    const container = document.getElementById('coursesList');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest('/api/student/courses');
        const courses = response.courses || [];

        if (courses.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📚</div>
                    <div class="empty-text">暂无课程，请联系老师分享课程</div>
                </div>
            `;
            return;
        }

        // 使用HTML转义防止XSS
        container.innerHTML = '<div class="courses-grid">' + courses.map(course => `
            <div class="course-card">
                <div class="course-card-header">
                    <div class="course-card-icon">📖</div>
                    <div class="course-card-info">
                        <div class="course-card-title">${escapeHtml(course.title || ((course.grade || '') + ' ' + (course.chapter || '')))}</div>
                        <div class="course-card-meta">
                            <span class="meta-tag">${escapeHtml(course.grade || '未分类')}</span>
                            <span class="meta-tag">${Object.keys(course.sections || {}).length} 章节</span>
                        </div>
                    </div>
                </div>
                <div class="course-card-body">
                    <p class="course-description">
                        ${escapeHtml(course.description || (course.sections && Object.keys(course.sections).length > 0 ? Object.keys(course.sections).join('、') : '暂无简介'))}
                    </p>
                    ${course.progress !== undefined ? `
                        <div class="course-progress-mini">
                            <div class="progress-bar-mini">
                                <div class="progress-fill-mini" style="width: ${course.progress}%"></div>
                            </div>
                            <span class="progress-text-mini">${course.progress}%</span>
                        </div>
                    ` : ''}
                </div>
                <div class="course-card-footer">
                    <span class="course-date">
                        ${course.created_at ? new Date(course.created_at).toLocaleDateString() : ''}
                    </span>
                    <div class="course-actions">
                        <button class="btn btn-primary btn-enter-course"
                                data-course-id="${escapeHtmlAttr(course.id)}"
                                data-course-title="${escapeHtmlAttr(course.title)}">
                            进入学习 →
                        </button>
                    </div>
                </div>
            </div>
        `).join('') + '</div>';

        // 绑定课程卡片按钮事件（学生端只有"进入学习"按钮）
        container.querySelectorAll('.btn-enter-course').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                enterCourseCatalog(courseId);
            });
        });

    } catch (error) {
        console.error('加载课程失败:', error);
        showToast(error.message, 'error');
        container.innerHTML = `<div class="empty-state"><div class="empty-text">加载失败，请重试</div></div>`;
    }
}

// 进入课程目录
function enterCourseCatalog(courseId) {
    window.location.hash = `#/student/catalog/${courseId}`;
    loadPage('/student/frontend/pages/course_catalog.html');
}

// 查看课程详情（保留旧函数兼容性）
// viewCourse 函数已移至第1891行，避免重复定义导致功能失效

// ==================== AI助教聊天 ====================
let agentSessionId = null;
let isAgentThinking = false;

function initAITutor() {
    console.log('[AI助教] 初始化聊天界面');

    // 获取或创建Agent会话
    if (!agentSessionId) {
        createAgentSession();
    }

    // 绑定发送按钮
    const sendBtn = document.getElementById('sendBtn');
    const chatInput = document.getElementById('chatInput');

    if (sendBtn && !sendBtn.dataset.initialized) {
        sendBtn.dataset.initialized = 'true';
        sendBtn.addEventListener('click', sendChatMessage);
    }

    // 绑定回车发送
    if (chatInput && !chatInput.dataset.initialized) {
        chatInput.dataset.initialized = 'true';
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChatMessage();
            }
        });
    }

    // 绑定快捷问题按钮
    document.querySelectorAll('.quick-question').forEach(btn => {
        if (!btn.dataset.initialized) {
            btn.dataset.initialized = 'true';
            btn.addEventListener('click', () => {
                const question = btn.dataset.question;
                if (chatInput) {
                    chatInput.value = question;
                    sendChatMessage();
                }
            });
        }
    });
}

async function createAgentSession() {
    try {
        const response = await apiRequest('/api/agent/chat', {
            method: 'POST',
            body: JSON.stringify({
                message: 'hello',
                create_session: true
            })
        });

        if (response.agent_id) {
            agentSessionId = response.agent_id;
            console.log('[AI助教] 会话已创建:', agentSessionId);
        }
    } catch (error) {
        console.error('[AI助教] 创建会话失败:', error);
        showToast('AI助教初始化失败', 'error');
    }
}

async function sendChatMessage() {
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    const messagesContainer = document.getElementById('chatMessages');

    if (!chatInput || !messagesContainer) return;

    const message = chatInput.value.trim();
    if (!message) return;

    if (isAgentThinking) {
        showToast('请等待AI回复', 'warning');
        return;
    }

    // 清空输入框
    chatInput.value = '';

    // 添加用户消息
    appendMessage('user', message);

    // 显示思考状态
    isAgentThinking = true;
    updateAgentStatus('thinking');
    appendThinkingIndicator();

    try {
        const response = await apiRequest('/api/agent/chat', {
            method: 'POST',
            body: JSON.stringify({
                message: message,
                agent_id: agentSessionId,
                agent_type: 'learning_tutor'
            })
        });

        // 移除思考指示器
        removeThinkingIndicator();

        if (response.success) {
            // 添加AI回复
            appendMessage('agent', response.response);

            // 保存会话ID
            if (response.agent_id) {
                agentSessionId = response.agent_id;
            }
        } else {
            appendMessage('agent', '抱歉，我遇到了一些问题，请稍后再试。');
        }
    } catch (error) {
        removeThinkingIndicator();
        appendMessage('agent', '抱歉，网络连接出现问题，请检查网络后重试。');
        console.error('[AI助教] 发送消息失败:', error);
    } finally {
        isAgentThinking = false;
        updateAgentStatus('online');
    }
}

function appendMessage(type, content) {
    const messagesContainer = document.getElementById('chatMessages');
    if (!messagesContainer) return;

    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${type === 'user' ? 'user-message' : 'agent-message'}`;

    const avatar = type === 'user' ? '我' : 'AI';

    // 处理内容格式（支持简单的markdown-like格式）
    const formattedContent = formatMessageContent(content);

    messageDiv.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div class="message-text">${formattedContent}</div>
            <div class="message-time">${new Date().toLocaleTimeString()}</div>
        </div>
    `;

    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // 渲染数学公式（MathJax）
    renderMathInElement(messageDiv);
}

// 渲染元素中的数学公式
function renderMathInElement(element) {
    if (window.MathJax && window.MathJax.typesetPromise) {
        // MathJax v3
        MathJax.typesetPromise([element]).catch((err) => {
            console.log('[MathJax] 渲染错误:', err);
        });
    } else if (window.MathJax && window.MathJax.typeset) {
        // MathJax v2
        try {
            MathJax.typeset([element]);
        } catch (e) {
            console.log('[MathJax] 渲染错误:', e);
        }
    }
}

function formatMessageContent(content) {
    if (typeof content !== 'string') return String(content);

    // 转义HTML
    let formatted = content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // 处理换行
    formatted = formatted.replace(/\n/g, '<br>');

    // 处理列表
    formatted = formatted.replace(/^\d+\.\s+/gm, '<strong>$&</strong>');
    formatted = formatted.replace(/^[-•]\s+/gm, '• ');

    // 处理加粗
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    return formatted;
}

function appendThinkingIndicator() {
    const messagesContainer = document.getElementById('chatMessages');
    if (!messagesContainer) return;

    const thinkingDiv = document.createElement('div');
    thinkingDiv.id = 'thinkingIndicator';
    thinkingDiv.className = 'chat-message agent-message';
    thinkingDiv.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="message-content">
            <div class="message-text">
                <span class="thinking-dots">思考中</span>
            </div>
        </div>
    `;

    messagesContainer.appendChild(thinkingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeThinkingIndicator() {
    const thinkingDiv = document.getElementById('thinkingIndicator');
    if (thinkingDiv) {
        thinkingDiv.remove();
    }
}

function updateAgentStatus(status) {
    const statusDiv = document.getElementById('agentStatus');
    if (!statusDiv) return;

    const indicator = statusDiv.querySelector('.status-indicator');
    const text = statusDiv.querySelector('span:last-child');

    if (indicator) {
        indicator.className = `status-indicator status-${status}`;
    }

    if (text) {
        switch (status) {
            case 'thinking':
                text.textContent = 'AI正在思考...';
                break;
            case 'online':
                text.textContent = 'AI助教在线中';
                break;
            case 'offline':
                text.textContent = 'AI助教离线';
                break;
        }
    }
}

// ==================== 学生加入班级 ====================
async function loadJoinClassPage() {
    loadMyClass();

    // 初始化搜索表单
    const searchForm = document.getElementById('searchClassForm');
    if (searchForm && !searchForm.dataset.initialized) {
        searchForm.dataset.initialized = 'true';
        searchForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const keyword = document.getElementById('searchKeyword').value.trim();
            await searchClasses(keyword);
        });
    }

    // 初始加载所有班级
    searchClasses('');
}

async function loadMyClass() {
    const container = document.getElementById('myClassInfo');
    if (!container) return;

    try {
        const user = state.currentUser;
        if (!user || !user.class) {
            container.innerHTML = '<p style="color: #999;">尚未加入任何班级</p>';
            return;
        }

        // 查找用户的班级
        const response = await apiRequest('/api/classes');
        const myClass = response.classes?.find(c => c.name === user.class);

        if (!myClass) {
            container.innerHTML = '<p style="color: #999;">尚未加入任何班级</p>';
            return;
        }

        container.innerHTML = `
            <div style="padding: 16px; background: #f5f5f5; border-radius: 8px;">
                <h4 style="margin-bottom: 8px;">${myClass.name}</h4>
                <div style="color: #666; margin-bottom: 12px;">
                    ${myClass.grade ? `年级: ${myClass.grade}` : ''}
                    ${myClass.description ? `<br>描述: ${myClass.description}` : ''}
                </div>
                <button class="btn btn-secondary" onclick="leaveClass('${myClass.id}', '${myClass.name}')">退出班级</button>
            </div>
        `;
    } catch (error) {
        container.innerHTML = '<p style="color: #f00;">加载班级信息失败</p>';
    }
}

async function searchClasses(keyword) {
    const container = document.getElementById('searchResults');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest(`/api/classes?keyword=${encodeURIComponent(keyword)}`);
        const classes = response.classes || [];

        if (classes.length === 0) {
            container.innerHTML = `
                <div class="card">
                    <p style="color: #999; text-align: center;">未找到匹配的班级</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="card">
                <h3 style="margin-bottom: 16px;">搜索结果 (${classes.length})</h3>
                ${classes.map(cls => `
                    <div style="padding: 12px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-weight: 600; margin-bottom: 4px;">${cls.name}</div>
                            <div style="color: #666; font-size: 14px;">
                                ${cls.grade ? `年级: ${cls.grade}` : ''} ${cls.grade && cls.description ? ' | ' : ''} ${cls.description || ''}
                                <br>学生: ${cls.student_count || 0} 人
                            </div>
                        </div>
                        ${cls.joined
                            ? '<span style="color: #4CAF50;">已加入</span>'
                            : `<button class="btn btn-primary" onclick="joinClass('${cls.id}', '${cls.name}')">加入</button>`
                        }
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        container.innerHTML = '<p style="color: #f00;">搜索失败</p>';
    }
}

async function joinClass(classId, className) {
    try {
        await apiRequest('/api/student/class/join', {
            method: 'POST',
            body: JSON.stringify({ class_id: classId })
        });
        showToast(`已加入 ${className}`, 'success');
        loadJoinClassPage();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function leaveClass(classId, className) {
    if (!confirm(`确定要退出班级"${className}"吗？`)) return;

    try {
        await apiRequest('/api/student/class/leave', {
            method: 'POST',
            body: JSON.stringify({ class_id: classId })
        });
        showToast('已退出班级', 'success');
        loadJoinClassPage();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ==================== 教师端逻辑 ====================
function initTeacherPage() {
    // 设置用户信息
    const userInfo = document.querySelector('.user-name');
    if (userInfo && state.currentUser) {
        userInfo.textContent = state.currentUser.username;
    }

    // 加载课程
    loadTeacherCourses();

    // 初始化班级管理表单（在导航事件之前初始化，确保表单绑定）
    initClassForm();

    // 导航事件
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            const target = item.dataset.target;
            document.querySelectorAll('.content-page').forEach(p => p.classList.remove('active'));
            document.getElementById(target).classList.add('active');

            // 加载对应内容
            if (target === 'courses') loadTeacherCourses();
            else if (target === 'generate') showGeneratePage();
            else if (target === 'classes') loadClasses();
            else if (target === 'students') loadStudents();
            else if (target === 'lessonPlans') loadTeacherLessonPlans();
        });
    });

    // 登出按钮
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    // 课程生成表单
    const generateForm = document.getElementById('generateForm');
    if (generateForm) {
        initGenerateForm();
    }

    // 视频生成页面
    initVideoPage();
}

// ==================== 视频生成功能 ====================
let currentVideoCourse = null;
let videoProgressInterval = null;

function initVideoPage() {
    const courseSelect = document.getElementById('videoCourseSelect');
    const loadBtn = document.getElementById('loadCourseForVideoBtn');
    const generateBtn = document.getElementById('generateVideoBtn');

    // 加载课程列表
    loadVideoCourses();

    // 课程选择变化
    if (courseSelect) {
        courseSelect.addEventListener('change', () => {
            loadBtn.disabled = !courseSelect.value;
        });
    }

    // 加载课程内容
    if (loadBtn) {
        loadBtn.addEventListener('click', loadCourseContentForVideo);
    }

    // 生成视频
    if (generateBtn) {
        generateBtn.addEventListener('click', generateCourseVideo);
    }
}

async function loadVideoCourses() {
    const courseSelect = document.getElementById('videoCourseSelect');
    if (!courseSelect) return;

    try {
        const response = await apiRequest('/api/teacher/courses');
        const courses = response.courses || [];

        courseSelect.innerHTML = '<option value="">请选择课程...</option>';
        courses.forEach(course => {
            const option = document.createElement('option');
            option.value = course.id;
            option.textContent = `${course.title || course.grade + course.chapter}`;
            courseSelect.appendChild(option);
        });
    } catch (error) {
        showToast('加载课程列表失败', 'error');
    }
}

async function loadCourseContentForVideo() {
    const courseSelect = document.getElementById('videoCourseSelect');
    const courseId = courseSelect.value;

    if (!courseId) {
        showToast('请先选择课程', 'warning');
        return;
    }

    try {
        const response = await apiRequest(`/course/${courseId}`);
        const course = response.result;

        if (!course) {
            showToast('课程不存在', 'error');
            return;
        }

        currentVideoCourse = course;

        // 显示课程内容
        const contentDiv = document.getElementById('videoCourseContent');
        const previewDiv = document.getElementById('videoCoursePreview');

        previewDiv.innerHTML = `
            <h4>${course.title}</h4>
            <p style="color: #666; margin-top: 8px;">
                <strong>年级:</strong> ${course.grade}<br>
                <strong>章节:</strong> ${course.chapter}<br>
                <strong>学生水平:</strong> ${course.student_level}<br>
                <strong>课程用途:</strong> ${course.purpose}
            </p>
        `;

        // 检查视频状态
        checkVideoStatus(courseId);

        contentDiv.style.display = 'block';

    } catch (error) {
        showToast('加载课程内容失败', 'error');
    }
}

async function checkVideoStatus(courseId) {
    try {
        const response = await apiRequest(`/api/video/course/${courseId}/status`);
        const status = response.status;

        const resultSection = document.getElementById('videoResultSection');
        const resultContent = document.getElementById('videoResultContent');

        if (status.has_video) {
            resultContent.innerHTML = `
                <p style="color: #4CAF50; margin-bottom: 16px;">
                    ✓ 视频已生成
                </p>
                <div style="margin-bottom: 16px;">
                    <strong>帧数:</strong> ${status.frame_count || 0}<br>
                    <strong>预计时长:</strong> ${status.estimated_duration || '未知'}
                </div>
                <video controls style="width: 100%; max-width: 600px; border-radius: 8px;" preload="metadata">
                    <source src="/api/video/course/${courseId}" type="video/mp4">
                    您的浏览器不支持视频播放
                </video>
            `;
            resultSection.style.display = 'block';
        } else {
            resultSection.style.display = 'none';
        }
    } catch (error) {
        console.error('检查视频状态失败:', error);
    }
}

async function generateCourseVideo() {
    if (!currentVideoCourse) {
        showToast('请先选择课程', 'warning');
        return;
    }

    const generateBtn = document.getElementById('generateVideoBtn');
    const progressSection = document.getElementById('videoProgressSection');
    const progressFill = document.getElementById('videoProgressFill');
    const progressMessage = document.getElementById('videoProgressMessage');

    // 构建课程内容
    let content = '';
    if (currentVideoCourse.content) {
        if (currentVideoCourse.content.sections) {
            const sections = currentVideoCourse.content.sections;
            content = Object.entries(sections).map(([key, value]) =>
                `${key}\n${value}`
            ).join('\n\n');
        } else if (currentVideoCourse.content.full_text) {
            content = currentVideoCourse.content.full_text;
        }
    }

    if (!content) {
        content = `课程标题: ${currentVideoCourse.title}\n年级: ${currentVideoCourse.grade}\n章节: ${currentVideoCourse.chapter}`;
    }

    try {
        generateBtn.disabled = true;
        progressSection.style.display = 'block';
        progressFill.style.width = '0%';
        progressMessage.textContent = '分析课程结构...';

        const response = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({
                course_id: currentVideoCourse.id,
                title: currentVideoCourse.title,
                content: content
            })
        });

        const taskId = response.task_id;

        // 轮询进度
        if (videoProgressInterval) {
            clearInterval(videoProgressInterval);
        }

        videoProgressInterval = setInterval(async () => {
            try {
                const progressResponse = await apiRequest(`/api/video/progress/${taskId}`);
                const progress = progressResponse.progress;

                progressFill.style.width = `${progress.percent}%`;
                progressMessage.textContent = progress.message;

                if (progress.status === 'completed') {
                    clearInterval(videoProgressInterval);
                    progressMessage.textContent = '生成完成！';
                    showToast('视频生成成功！', 'success');

                    // 刷新视频状态
                    checkVideoStatus(currentVideoCourse.id);

                    setTimeout(() => {
                        progressSection.style.display = 'none';
                        generateBtn.disabled = false;
                    }, 2000);

                } else if (progress.status === 'failed') {
                    clearInterval(videoProgressInterval);
                    progressMessage.textContent = `生成失败: ${progress.message}`;
                    showToast('视频生成失败', 'error');
                    generateBtn.disabled = false;
                }

            } catch (error) {
                console.error('获取进度失败:', error);
            }
        }, 2000);

    } catch (error) {
        showToast(error.message, 'error');
        generateBtn.disabled = false;
        progressSection.style.display = 'none';
    }
}

// ==================== 自动视频生成（课程生成后触发）====================
async function startVideoGeneration(courseId) {
    try {
        // 获取课程详情
        const courseResponse = await apiRequest(`/api/teacher/courses`);
        const course = courseResponse.courses?.find(c => c.id === courseId);

        if (!course) {
            showToast('无法找到课程信息', 'error');
            return;
        }

        // 构建课程内容
        let content = '';
        if (course.content) {
            if (course.content.sections) {
                const sections = course.content.sections;
                content = Object.entries(sections).map(([key, value]) =>
                    `${key}\n${value}`
                ).join('\n\n');
            } else if (course.content.full_text) {
                content = course.content.full_text;
            }
        }

        if (!content) {
            content = `课程标题: ${course.title}\n年级: ${course.grade}\n章节: ${course.chapter}`;
        }

        // 调用视频生成API
        const response = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({
                course_id: course.id,
                title: course.title,
                content: content
            })
        });

        const taskId = response.task_id;
        showToast('视频生成任务已启动，请在"视频生成"页面查看进度', 'success');

        // 可选：自动切换到视频生成页面
        // window.location.hash = '#/teacher/video';
        // document.querySelector('[data-target="video"]').click();

    } catch (error) {
        console.error('启动视频生成失败:', error);
        showToast('启动视频生成失败: ' + error.message, 'error');
    }
}

async function loadTeacherCourses() {
    const container = document.getElementById('teacherCoursesList');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest('/api/teacher/courses');
        const courses = response.courses || [];

        if (courses.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">[BOOK]</div>
                    <div class="empty-text">还没有生成过课程</div>
                    <button class="btn btn-primary btn-start-generate">开始生成</button>
                </div>
            `;
            // 绑定"开始生成"按钮事件
            const startBtn = container.querySelector('.btn-start-generate');
            if (startBtn) {
                startBtn.addEventListener('click', () => {
                    const generateNav = document.querySelector('[data-target="generate"]');
                    if (generateNav) generateNav.click();
                });
            }
            return;
        }

        container.innerHTML = `<div class="course-grid">${courses.map(course => `
            <div class="course-card">
                <div class="course-card-header">
                    <div class="course-card-title">${(course.title || course.grade + course.chapter).replace(/'/g, '&#39;')}</div>
                    <div class="course-card-meta">${course.grade} · ${course.chapter}</div>
                </div>
                <div class="course-card-body">
                    <p style="color: #666; font-size: 14px;">
                        ${course.sections && Object.keys(course.sections).length > 0 ? Object.keys(course.sections).slice(0, 3).join('、') : '暂无简介'}
                    </p>
                </div>
                <div class="course-card-footer">
                    <button class="btn btn-secondary btn-view-course" data-course-id="${course.id.replace(/'/g, "\\'")}" style="font-size: 14px; padding: 8px 16px;">
                        预览
                    </button>
                    <button class="btn btn-secondary btn-generate-video" data-course-id="${course.id.replace(/'/g, "\\'")}" style="font-size: 14px; padding: 8px 16px;">
                        🎬 生成视频
                    </button>
                    <button class="btn btn-secondary btn-share-course" data-course-id="${course.id.replace(/'/g, "\\'")}" style="font-size: 14px; padding: 8px 16px;">
                        分享
                    </button>
                </div>
            </div>
        `).join('')}</div>`;

        // 绑定按钮事件（使用事件委托）
        container.querySelectorAll('.btn-view-course').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                window.viewCourse(courseId);
            });
        });
        container.querySelectorAll('.btn-generate-video').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                window.generateCourseVideoFromCard(courseId);
            });
        });
        container.querySelectorAll('.btn-share-course').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                window.shareCourse(courseId);
            });
        });
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function loadStudents() {
    const container = document.getElementById('studentsList');
    const classSelect = document.getElementById('classSelect');

    if (!container) return;

    const selectedClass = classSelect ? classSelect.value : '七年级1班';

    try {
        const response = await apiRequest(`/api/teacher/students?class_name=${encodeURIComponent(selectedClass)}`);
        const students = response.students || [];

        if (students.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-text">该班级暂无学生</div>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 2px solid #e5e7eb;">
                        <th style="padding: 12px; text-align: left;">姓名</th>
                        <th style="padding: 12px; text-align: left;">学号</th>
                        <th style="padding: 12px; text-align: left;">班级</th>
                    </tr>
                </thead>
                <tbody>
                    ${students.map(s => `
                        <tr style="border-bottom: 1px solid #f3f4f6;">
                            <td style="padding: 12px;">${s.username}</td>
                            <td style="padding: 12px;">${s.student_id || '-'}</td>
                            <td style="padding: 12px;">${s.class || '-'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function loadTeacherLessonPlans() {
    const container = document.getElementById('teacherLessonPlansList');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest('/api/teacher/lesson-plans');
        const lessonPlans = response.lesson_plans || [];

        if (lessonPlans.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">[BOOK]</div>
                    <div class="empty-text">还没有保存教案</div>
                    <div class="empty-hint">生成课程后可保存为教案，方便后续查看和复用</div>
                </div>
            `;
            return;
        }

        lessonPlans.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

        container.innerHTML = lessonPlans.map(plan => `
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div style="flex: 1;">
                        <div style="font-weight: 600; margin-bottom: 8px;">${plan.title}</div>
                        <div style="color: #666; font-size: 14px; margin-bottom: 8px;">
                            ${plan.grade || ''} ${plan.chapter || ''} | ${plan.lesson_type || '课程'}
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ==================== 班级管理 ====================
function initClassForm() {
    // 初始化创建班级表单
    const createForm = document.getElementById('createClassForm');
    if (createForm && !createForm.dataset.initialized) {
        createForm.dataset.initialized = 'true';
        createForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('className').value.trim();
            const grade = document.getElementById('classGrade').value;
            const description = document.getElementById('classDesc').value.trim();

            if (!name) {
                showToast('请输入班级名称', 'error');
                return;
            }

            try {
                await apiRequest('/api/teacher/class', {
                    method: 'POST',
                    body: JSON.stringify({ name, grade, description })
                });
                showToast('班级创建成功', 'success');
                createForm.reset();
                loadClasses();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    }
}

async function loadClasses() {
    const container = document.getElementById('classList');
    if (!container) return;

    try {
        const response = await apiRequest('/api/teacher/classes');
        const classes = response.classes || [];

        if (classes.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">[GROUP]</div>
                    <div class="empty-text">还没有创建班级</div>
                </div>
            `;
            return;
        }

        container.innerHTML = classes.map(cls => `
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div style="flex: 1;">
                        <h3 style="margin-bottom: 8px;">${cls.name}</h3>
                        <div style="color: #666; margin-bottom: 12px;">
                            ${cls.grade ? `<span style="margin-right: 16px;">年级: ${cls.grade}</span>` : ''}
                            <span>学生: ${cls.student_ids?.length || 0} 人</span>
                        </div>
                        ${cls.description ? `<div style="color: #999; font-size: 14px; margin-bottom: 12px;">${cls.description}</div>` : ''}
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary" onclick="viewClassStudents('${cls.id}', '${cls.name}')">查看学生</button>
                        <button class="btn btn-danger" onclick="deleteClass('${cls.id}', '${cls.name}')">删除</button>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function deleteClass(classId, className) {
    if (!confirm(`确定要删除班级"${className}"吗？`)) return;

    try {
        await apiRequest(`/api/teacher/class/${classId}`, {
            method: 'DELETE'
        });
        showToast('班级已删除', 'success');
        loadClasses();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function viewClassStudents(classId, className) {
    try {
        const response = await apiRequest(`/api/class/${classId}/students`);
        const students = response.students || [];

        const studentList = students.length > 0
            ? students.map(s => `
                <tr>
                    <td>${s.username}</td>
                    <td>${s.student_id || '-'}</td>
                    <td>${s.email || '-'}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="3" style="text-align: center; color: #999;">暂无学生</td></tr>';

        // 显示学生列表弹窗
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 600px;">
                <div class="modal-header">
                    <h3>${className} - 学生列表</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <table>
                        <thead>
                            <tr>
                                <th>姓名</th>
                                <th>学号</th>
                                <th>邮箱</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${studentList}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function showGeneratePage() {
    // 课程生成页面已包含在 HTML 中
}

// ==================== 生成课程全局变量 ====================
let currentTaskId = null;
let currentGeneratedCourseId = null; // 当前生成的课程ID

function initGenerateForm() {
    const versionSelect = document.getElementById('version');
    const gradeSelect = document.getElementById('grade');
    const chapterSelect = document.getElementById('chapter');
    const generateForm = document.getElementById('generateForm');
    const progressSection = document.getElementById('progressSection');
    const resultSection = document.getElementById('resultSection');

    // 检查generateVideo元素是否存在
    const generateVideoCheckbox = document.getElementById('generateVideo');

    // 内容源切换
    const contentSourceRadios = document.querySelectorAll('input[name="contentSource"]');
    const textbookSection = document.getElementById('textbookSection');
    const customSection = document.getElementById('customSection');

    contentSourceRadios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            if (e.target.value === 'textbook') {
                textbookSection.style.display = 'block';
                customSection.style.display = 'none';
                // 重置教材选择的 required 属性
                versionSelect.required = true;
                gradeSelect.required = true;
                chapterSelect.required = true;
                document.getElementById('customTitle').required = false;
                document.getElementById('customOutline').required = false;
            } else {
                textbookSection.style.display = 'none';
                customSection.style.display = 'block';
                // 重置自定义输入的 required 属性
                versionSelect.required = false;
                gradeSelect.required = false;
                chapterSelect.required = false;
                document.getElementById('customTitle').required = true;
                document.getElementById('customOutline').required = true;
            }
        });
    });

    // 加载教材版本
    loadTextbookVersions();

    versionSelect.addEventListener('change', async () => {
        const version = versionSelect.value;
        if (!version) return;

        gradeSelect.disabled = true;
        gradeSelect.innerHTML = '<option value="">加载中...</option>';

        try {
            const response = await apiRequest(`/textbooks/${version}/grades`);
            const grades = response.grades || [];

            gradeSelect.innerHTML = '<option value="">请选择年级</option>';
            grades.forEach(grade => {
                const option = document.createElement('option');
                option.value = grade;
                option.textContent = grade;
                gradeSelect.appendChild(option);
            });
            gradeSelect.disabled = false;
        } catch (error) {
            showToast('加载年级失败', 'error');
        }
    });

    gradeSelect.addEventListener('change', async () => {
        const version = versionSelect.value;
        const grade = gradeSelect.value;
        if (!version || !grade) return;

        chapterSelect.disabled = true;
        chapterSelect.innerHTML = '<option value="">加载中...</option>';

        try {
            // 对年级参数进行URL编码，支持中文
            const encodedGrade = encodeURIComponent(grade);
            const response = await apiRequest(`/textbooks/${version}/${encodedGrade}/chapters`);
            const chapters = response.chapters || [];

            chapterSelect.innerHTML = '<option value="">请选择章节</option>';
            chapters.forEach(chapter => {
                const option = document.createElement('option');
                option.value = chapter.id;
                option.textContent = chapter.name;
                chapterSelect.appendChild(option);
            });
            chapterSelect.disabled = false;
        } catch (error) {
            showToast('加载章节失败', 'error');
        }
    });

    generateForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // 获取选择的内容源
        const contentSource = document.querySelector('input[name="contentSource"]:checked').value;

        let requestData = {
            with_examples: document.getElementById('withExamples').checked,
            with_exercises: document.getElementById('withExercises').checked,
            generate_video: document.getElementById('generateVideo').checked
        };

        // 根据内容源设置不同的参数
        if (contentSource === 'textbook') {
            // 教材章节模式：生成学生课件，固定用途为"学生自学"
            requestData.student_level = document.getElementById('studentLevel').value;
            requestData.purpose = '学生自学';
            requestData.version = versionSelect.value;
            requestData.grade = gradeSelect.value;
            requestData.chapter_id = chapterSelect.value;
        } else {
            // 自定义内容模式：教师专用，根据选择的类型生成
            requestData.student_level = '保持原风格';
            requestData.content_type = document.getElementById('contentType').value;

            const customTitle = document.getElementById('customTitle').value.trim();
            const customOutline = document.getElementById('customOutline').value.trim();

            if (!customTitle) {
                showToast('请输入课程标题', 'error');
                return;
            }
            if (!customOutline) {
                showToast('请输入课程大纲内容', 'error');
                return;
            }

            requestData.custom_topic = customTitle;
            requestData.custom_outline = customOutline;
            requestData.version = 'custom';
            requestData.grade = '自定义';
            requestData.chapter_id = 'custom';

            // 根据内容类型设置purpose
            const contentTypeToPurpose = {
                'lesson_plan': '教师备课教案',
                'teaching_script': '课堂讲解逐字稿',
                'board_design': '板书设计',
                'review_outline': '复习串讲'
            };
            requestData.purpose = contentTypeToPurpose[requestData.content_type] || '自定义内容';
        }

        // 显示进度
        progressSection.style.display = 'block';
        resultSection.style.display = 'none';
        const progressFill = document.getElementById('progressFill');
        const progressMessage = document.getElementById('progressMessage');

        try {
            // 提交生成任务
            const response = await apiRequest('/generate/course', {
                method: 'POST',
                body: JSON.stringify(requestData)
            });

            currentTaskId = response.task_id;

            // 轮询进度
            pollProgress();

        } catch (error) {
            showToast(error.message, 'error');
            progressSection.style.display = 'none';
        }
    });

    async function pollProgress() {
        if (!currentTaskId) return;

        try {
            const response = await apiRequest(`/progress/${currentTaskId}`);
            const progress = response.progress || 0;
            const message = response.message || '处理中...';

            progressFill.style.width = `${progress}%`;
            progressMessage.textContent = message;

            if (response.status === 'completed') {
                // 完成 - 显示预览界面
                progressSection.style.display = 'none';
                await showPreviewSection(currentTaskId);
                showToast('课程生成成功！请预览确认', 'success');
            } else if (response.status === 'failed') {
                // 失败
                progressSection.style.display = 'none';
                showToast(`生成失败：${response.error || '未知错误'}`, 'error');
            } else {
                // 继续轮询
                setTimeout(pollProgress, 1000);
            }
        } catch (error) {
            showToast('获取进度失败', 'error');
        }
    }

    window.exportResult = async function(format) {
        if (!currentTaskId) {
            showToast('没有可导出的课程', 'error');
            return;
        }

        window.open(`${API_BASE}/export/${format}/${currentTaskId}?session_id=${state.sessionId}`, '_blank');
    };
}

// ==================== 全局函数 ====================

// 预览课程内容
async function showPreviewSection(taskId) {
    try {
        const response = await apiRequest(`/course/${taskId}/preview`);
        const { content, validation, generate_video } = response;

        const previewSection = document.getElementById('previewSection');
        const previewContent = document.getElementById('previewContent');
        const validationResult = document.getElementById('validationResult');
        const validationStatus = document.getElementById('validationStatus');

        // 显示验证状态
        if (validation) {
            if (validation.is_valid && !validation.has_warnings) {
                validationStatus.innerHTML = '✓ 校验通过';
                validationStatus.style.background = '#d1fae5';
                validationStatus.style.color = '#065f46';
            } else if (validation.is_valid && validation.has_warnings) {
                validationStatus.innerHTML = `⚠ 通过（${validation.warnings?.length || 0}个警告）`;
                validationStatus.style.background = '#fef3c7';
                validationStatus.style.color = '#92400e';
            } else {
                validationStatus.innerHTML = `✗ 校验失败（${validation.errors?.length || 0}个错误）`;
                validationStatus.style.background = '#fee2e2';
                validationStatus.style.color = '#991b1b';
            }

            // 显示验证详情
            if (validation.errors && validation.errors.length > 0) {
                validationResult.innerHTML = `
                    <div style="background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 8px; margin-bottom: 12px;">
                        <strong>错误：</strong>
                        <ul style="margin: 8px 0 0 20px;">
                            ${validation.errors.map(e => `<li>${e}</li>`).join('')}
                        </ul>
                    </div>
                `;
            } else if (validation.warnings && validation.warnings.length > 0) {
                validationResult.innerHTML = `
                    <div style="background: #fef3c7; color: #92400e; padding: 12px; border-radius: 8px; margin-bottom: 12px;">
                        <strong>警告：</strong>
                        <ul style="margin: 8px 0 0 20px;">
                            ${validation.warnings.map(w => `<li>${w}</li>`).join('')}
                        </ul>
                    </div>
                `;
            } else {
                validationResult.innerHTML = '';
            }
        }

        // 显示内容预览
        previewContent.innerHTML = `
            <h4 style="margin-bottom: 12px;">${content.title || '课程标题'}</h4>
            ${Object.entries(content.sections || {}).map(([key, value]) => `
                <div style="margin-bottom: 16px;">
                    <h5 style="color: #2a78ff; margin-bottom: 8px;">${key}</h5>
                    <div style="color: #666; line-height: 1.6; white-space: pre-wrap;">${value?.substring(0, 500)}${value?.length > 500 ? '...' : ''}</div>
                </div>
            `).join('')}
        `;

        // 绑定按钮事件（传递generate_video标志）
        bindPreviewButtons(taskId, content, generate_video || false);

        previewSection.style.display = 'block';
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 绑定预览界面按钮事件
function bindPreviewButtons(taskId, content, generateVideoFlag = false) {
    const saveBtn = document.getElementById('saveCourseBtn');
    const editBtn = document.getElementById('editCourseBtn');
    const regenerateBtn = document.getElementById('regenerateBtn');
    const cancelBtn = document.getElementById('cancelPreviewBtn');

    // 保存课程
    saveBtn.onclick = async () => {
        try {
            const response = await apiRequest(`/course/${taskId}/save`, {
                method: 'POST'
            });
            const courseId = response.course_id;
            currentGeneratedCourseId = courseId;

            showToast('课程已保存', 'success');
            document.getElementById('previewSection').style.display = 'none';

            // 如果勾选了生成视频，自动触发视频生成
            if (generateVideoFlag && courseId) {
                showToast('正在启动视频生成...', 'info');
                await startVideoGeneration(courseId);
            }

            loadTeacherCourses(); // 刷新课程列表
        } catch (error) {
            showToast(error.message, 'error');
        }
    };

    // 编辑内容
    editBtn.onclick = () => {
        showEditSection(content);
    };

    // 重新生成
    regenerateBtn.onclick = () => {
        document.getElementById('previewSection').style.display = 'none';
        document.getElementById('generateForm').reset();
        document.querySelector('input[name="contentSource"][value="textbook"]').checked = true;
        document.getElementById('textbookSection').style.display = 'block';
        document.getElementById('customSection').style.display = 'none';
        showToast('请重新填写生成参数', 'info');
    };

    // 取消
    cancelBtn.onclick = () => {
        document.getElementById('previewSection').style.display = 'none';
    };
}

// 生成有效的HTML ID
function generateValidId(prefix, key) {
    // 将key转换为有效的HTML ID：移除特殊字符，用下划线替换
    const sanitized = key.replace(/[^a-zA-Z0-9_-]/g, '_');
    return `${prefix}_${sanitized}`;
}

// 显示编辑界面
function showEditSection(content) {
    const editSection = document.getElementById('editSection');
    const editForm = document.getElementById('editForm');
    const previewSection = document.getElementById('previewSection');

    previewSection.style.display = 'none';

    // 创建key到ID的映射
    const keyToIdMap = {};
    Object.keys(content.sections || {}).forEach(key => {
        keyToIdMap[key] = generateValidId('edit', key);
    });

    editForm.innerHTML = `
        <div class="form-group">
            <label for="editTitle">课程标题</label>
            <input type="text" id="editTitle" class="form-control" value="${content.title || ''}">
        </div>
        ${Object.entries(content.sections || {}).map(([key, value]) => {
            const validId = keyToIdMap[key];
            return `
            <div class="form-group" style="margin-top: 16px;">
                <label for="${validId}">${key}</label>
                <textarea id="${validId}" class="form-control" rows="6">${value || ''}</textarea>
            </div>
            `;
        }).join('')}
    `;

    // 绑定编辑按钮事件
    const saveEditBtn = document.getElementById('saveEditBtn');
    const cancelEditBtn = document.getElementById('cancelEditBtn');

    saveEditBtn.onclick = () => {
        // 保存编辑后的内容
        const editedContent = {
            title: document.getElementById('editTitle').value,
            sections: {}
        };

        Object.keys(content.sections || {}).forEach(key => {
            const validId = keyToIdMap[key];
            const element = document.getElementById(validId);
            if (element) {
                editedContent.sections[key] = element.value;
            } else {
                console.warn(`Element not found for key: ${key}, id: ${validId}`);
            }
        });

        // 更新预览
        showPreviewSectionWithContent(editedContent);
    };

    cancelEditBtn.onclick = () => {
        editSection.style.display = 'none';
        previewSection.style.display = 'block';
    };

    editSection.style.display = 'block';
}

// 使用编辑后的内容显示预览
function showPreviewSectionWithContent(content) {
    document.getElementById('editSection').style.display = 'none';

    const previewSection = document.getElementById('previewSection');
    const previewContent = document.getElementById('previewContent');

    previewContent.innerHTML = `
        <h4 style="margin-bottom: 12px;">${content.title || '课程标题'}</h4>
        ${Object.entries(content.sections || {}).map(([key, value]) => `
            <div style="margin-bottom: 16px;">
                <h5 style="color: #2a78ff; margin-bottom: 8px;">${key}</h5>
                <div style="color: #666; line-height: 1.6; white-space: pre-wrap;">${value?.substring(0, 500)}${value?.length > 500 ? '...' : ''}</div>
            </div>
        `).join('')}
    `;

    previewSection.style.display = 'block';
}

// 版本对比功能
async function showVersionCompare(courseId) {
    try {
        const response = await apiRequest(`/course/${courseId}/versions`);
        const versions = response.versions || [];

        if (versions.length < 2) {
            showToast('需要至少两个版本才能对比', 'error');
            return;
        }

        // 显示版本选择界面
        const compareSection = document.getElementById('compareSection');
        const compareContent = document.getElementById('compareContent');

        compareContent.innerHTML = `
            <div class="form-group">
                <label>选择版本1</label>
                <select id="version1Select" class="form-control form-select">
                    ${versions.map(v => `
                        <option value="${v.id}">版本 ${v.version_number} (${new Date(v.created_at).toLocaleString()})</option>
                    `).join('')}
                </select>
            </div>
            <div class="form-group" style="margin-top: 12px;">
                <label>选择版本2</label>
                <select id="version2Select" class="form-control form-select">
                    ${versions.map((v, i) => `
                        <option value="${v.id}" ${i === versions.length - 2 ? 'selected' : ''}>版本 ${v.version_number} (${new Date(v.created_at).toLocaleString()})</option>
                    `).join('')}
                </select>
            </div>
            <button class="btn btn-primary" id="doCompareBtn" style="margin-top: 16px;">开始对比</button>
            <div id="compareResult" style="margin-top: 20px;"></div>
        `;

        // 绑定对比按钮事件
        document.getElementById('doCompareBtn').onclick = async () => {
            const version1 = document.getElementById('version1Select').value;
            const version2 = document.getElementById('version2Select').value;

            if (version1 === version2) {
                showToast('请选择不同的版本进行对比', 'error');
                return;
            }

            const compareResponse = await apiRequest(`/course/version/${version1}/compare/${version2}`);
            const comparison = compareResponse.comparison;

            document.getElementById('compareResult').innerHTML = `
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 16px;">
                    <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: #fafafa;">
                        <h4 style="color: #2a78ff; margin-bottom: 12px;">版本 ${comparison.version1.number}</h4>
                        <div><strong>标题：</strong>${comparison.version1.title}</div>
                        <div><strong>章节数：</strong>${comparison.version1.sections_count}</div>
                        <div><strong>创建时间：</strong>${new Date(comparison.version1.created_at).toLocaleString()}</div>
                        <div style="margin-top: 12px; white-space: pre-wrap; max-height: 300px; overflow-y: auto;">${comparison.version1.content?.substring?.(0, 500) || '无内容预览'}</div>
                    </div>
                    <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: #fafafa;">
                        <h4 style="color: #7a41ff; margin-bottom: 12px;">版本 ${comparison.version2.number}</h4>
                        <div><strong>标题：</strong>${comparison.version2.title}</div>
                        <div><strong>章节数：</strong>${comparison.version2.sections_count}</div>
                        <div><strong>创建时间：</strong>${new Date(comparison.version2.created_at).toLocaleString()}</div>
                        <div style="margin-top: 12px; white-space: pre-wrap; max-height: 300px; overflow-y: auto;">${comparison.version2.content?.substring?.(0, 500) || '无内容预览'}</div>
                    </div>
                </div>
            `;
        };

        // 绑定关闭按钮事件
        document.getElementById('cancelCompareBtn').onclick = () => {
            compareSection.style.display = 'none';
        };

        compareSection.style.display = 'block';
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 查看课程详情（教师端预览功能）
window.viewCourse = async function(courseId) {
    console.log('[viewCourse] Called with courseId:', courseId);
    try {
        console.log('[viewCourse] Fetching courses...');
        const response = await apiRequest(`/api/teacher/courses`);
        console.log('[viewCourse] Response:', response);
        const course = response.courses?.find(c => c.id === courseId);
        console.log('[viewCourse] Found course:', course);

        if (!course) {
            console.error('[viewCourse] Course not found!');
            showToast('课程不存在', 'error');
            return;
        }

        // 直接从 course.sections 获取章节内容
        const sections = course.sections || {};
        console.log('[viewCourse] Course sections:', Object.keys(sections));

        // 创建预览弹窗
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.cssText = 'display: flex !important; position: fixed !important; top: 0 !important; left: 0 !important; width: 100% !important; height: 100% !important; background: rgba(0,0,0,0.5) !important; z-index: 10000 !important; align-items: center !important; justify-content: center !important;';
        console.log('[viewCourse] Creating modal...');
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 800px; max-height: 80vh; overflow-y: auto;">
                <div class="modal-header">
                    <h3>${course.title || '课程详情'}</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <div style="margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb;">
                        <div style="color: #666; font-size: 14px; margin-bottom: 8px;">
                            <span style="margin-right: 16px;">📚 ${course.grade || ''}</span>
                            <span>📖 ${course.chapter || ''}</span>
                        </div>
                        <div style="color: #999; font-size: 13px;">
                            创建时间: ${course.created_at ? new Date(course.created_at).toLocaleString('zh-CN') : '未知'}
                        </div>
                    </div>
                    <div style="max-height: 500px; overflow-y: auto;">
                        ${Object.entries(sections).map(([key, value]) => `
                            <div style="margin-bottom: 24px;">
                                <h4 style="color: #2a78ff; margin-bottom: 12px; font-size: 16px;">${key}</h4>
                                <div style="color: #333; line-height: 1.8; white-space: pre-wrap; font-size: 14px;">${value || '暂无内容'}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">关闭</button>
                    <button class="btn btn-primary" onclick="shareCourse('${courseId}')">分享到班级</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        console.log('[viewCourse] Modal appended to body');

        // 点击背景关闭
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

    } catch (error) {
        console.error('[viewCourse] Error:', error);
        showToast('加载课程详情失败: ' + error.message, 'error');
    }
};

// 从课程卡片直接生成视频
window.generateCourseVideoFromCard = async function(courseId) {
    try {
        // 获取课程详情
        const response = await apiRequest('/api/teacher/courses');
        const course = response.courses?.find(c => c.id === courseId);

        if (!course) {
            showToast('无法找到课程信息', 'error');
            return;
        }

        // 构建课程内容
        let content = '';
        if (course.content) {
            if (course.content.sections) {
                const sections = course.content.sections;
                content = Object.entries(sections).map(([key, value]) =>
                    `${key}\n${value}`
                ).join('\n\n');
            } else if (course.content.full_text) {
                content = course.content.full_text;
            }
        }

        if (!content) {
            content = `课程标题: ${course.title}\n年级: ${course.grade}\n章节: ${course.chapter}`;
        }

        // 确认生成
        if (!confirm(`确定要为课程"${course.title}"生成讲解视频吗？`)) {
            return;
        }

        const videoResponse = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({
                course_id: course.id,
                title: course.title,
                content: content
            })
        });

        const taskId = videoResponse.task_id;
        showToast('视频生成任务已启动，请在"视频生成"页面查看进度', 'success');

        // 询问是否跳转到视频生成页面
        setTimeout(() => {
            if (confirm('是否跳转到"视频生成"页面查看进度？')) {
                document.querySelector('[data-target="video"]').click();
            }
        }, 500);

    } catch (error) {
        console.error('启动视频生成失败:', error);
        showToast('启动视频生成失败: ' + error.message, 'error');
    }
};

window.shareCourse = async function(courseId) {
    console.log('[shareCourse] Called with courseId:', courseId);
    // 分享课程到班级
    try {
        console.log('[shareCourse] Fetching classes...');
        // 获取教师的班级列表
        const response = await apiRequest('/api/teacher/classes');
        console.log('[shareCourse] Classes response:', response);
        const classes = response.classes || [];

        if (classes.length === 0) {
            console.error('[shareCourse] No classes found!');
            showToast('请先创建班级', 'error');
            return;
        }

        console.log('[shareCourse] Found classes:', classes.length);

        // 创建分享对话框
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.cssText = 'display: flex !important; position: fixed !important; top: 0 !important; left: 0 !important; width: 100% !important; height: 100% !important; background: rgba(0,0,0,0.5) !important; z-index: 10000 !important; align-items: center !important; justify-content: center !important;';
        console.log('[shareCourse] Creating modal...');
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 500px;">
                <div class="modal-header">
                    <h3>分享课程到班级</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label for="shareClassSelect">选择班级</label>
                        <select id="shareClassSelect" class="form-control form-select">
                            ${classes.map(cls =>
                                `<option value="${cls.id}">${cls.name} (${cls.student_ids?.length || 0}人)</option>`
                            ).join('')}
                        </select>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
                    <button class="btn btn-primary" id="confirmShareBtn">确认分享</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        console.log('[shareCourse] Modal appended to body');

        // 点击背景关闭
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

        // 确认分享
        document.getElementById('confirmShareBtn').addEventListener('click', async () => {
            const classId = document.getElementById('shareClassSelect').value;

            try {
                await apiRequest('/api/teacher/share', {
                    method: 'POST',
                    body: JSON.stringify({
                        course_id: courseId,
                        class_id: classId
                    })
                });
                showToast('分享成功！', 'success');
                modal.remove();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        console.error('[shareCourse] Error:', error);
        showToast(error.message, 'error');
    }
};

// ==================== 应用初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
});

// ==================== 加载教材版本 ====================
async function loadTextbookVersions() {
    const versionSelect = document.getElementById('version');
    if (!versionSelect) return;

    try {
        const response = await apiRequest('/textbooks/versions');
        const versions = response.versions || [];

        versionSelect.innerHTML = '<option value="">请选择教材版本</option>';
        versions.forEach(version => {
            const option = document.createElement('option');
            option.value = version.id;
            option.textContent = version.name;
            versionSelect.appendChild(option);
        });
    } catch (error) {
        showToast('加载教材版本失败', 'error');
    }
}
