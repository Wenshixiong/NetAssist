// 简易 Toast 提示
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 px-4 py-2 rounded-md shadow-lg text-white z-50 transition-opacity duration-300 ${type === 'success' ? 'bg-green-500' : 'bg-red-500'
        }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// 设备类型配置（添加图标路径）
const deviceTypeConfig = {
    '交换机': {
        label: '交换机',
        icon: '/static/icons/交换机.png'
    },
    '路由器': {
        label: '路由器',
        icon: '/static/icons/路由器.png'
    },
    '防火墙': {
        label: '防火墙',
        icon: '/static/icons/防火墙.png'
    },
    '负载均衡': {
        label: '负载均衡',
        icon: '/static/icons/负载均衡.png'
    },
    '网管平台': {
        label: '网管平台',
        icon: '/static/icons/网管平台.png'
    },
    '云管平台': {
        label: '云管平台',
        icon: '/static/icons/云管平台.png'
    },
    '服务器集群': {
        label: '服务器集群',
        icon: '/static/icons/服务器集群.png'
    },
    '清洗检测': {
        label: '清洗检测',
        icon: '/static/icons/清洗检测.png'
    },
    '未知': {
        label: '未知设备',
        color: '#9ca3af',
        icon: null
    }
};

// 定义图例渲染函数
function renderDeviceLegend() {
    const legendContainer = document.getElementById('device-legend');
    // 设置为两列网格
    legendContainer.style.display = 'grid';
    legendContainer.style.gridTemplateColumns = '1fr 1fr';
    legendContainer.style.gap = '4px 12px'; // 行间距4px，列间距12px
    legendContainer.innerHTML = '';
    Object.values(deviceTypeConfig).forEach(type => {
        const legendItem = document.createElement('div');
        legendItem.className = 'flex items-center py-1';

        let legendContent = '';
        if (type.icon && type.icon !== null) {
            legendContent = `
                <img src="${type.icon}" alt="${type.label}" 
                    class="w-5 h-5 mr-2 object-contain">
                <span class="text-xs text-gray-700">${type.label}</span>
            `;
        } else {
            legendContent = `
                <div class="w-5 h-5 rounded-full mr-2" style="background-color: ${type.color}"></div>
                <span class="text-xs text-gray-700">${type.label}</span>
            `;
        }

        legendItem.innerHTML = legendContent;
        legendContainer.appendChild(legendItem);
    });
}




// ====== 页面加载完成时：首次加载拓扑 ======
document.addEventListener('DOMContentLoaded', function () {
    renderDeviceLegend();
    // 默认锁定布局：用户进入即不可拖动，仅可查看 tooltip
    window.isLayoutLocked = true;
    // 初始加载
    loadTopology();


    // ====== 改动点1：将 cy 改为全局 window.cy，并将初始化代码提取为 initCytoscape 函数 ======
    function initCytoscape() {
        // 如果已经有实例，先销毁（防御）
        if (window.cy) {
            if (typeof window.cy.destroy === 'function') {
                window.cy.destroy();
            }
            window.cy = null;
        }

        window.cy = cytoscape({
            wheelSensitivity: 0.1,
            pixelRatio: 1, // 保持像素比一致，避免缩放问题
            // minZoom: 0.05,
            // maxZoom: 15,
            // zoomingEnabled: true, // 新增：允许代码调用缩放
            // userZoomingEnabled: false, // 用户原生滚轮缩放关闭
            zoom: 1,
            container: document.getElementById('cy'),
            boxSelectionEnabled: true,
            selectionType: 'single', // 单次单选：单击只保留当前选中
            selectionModifiers: 'ctrl meta', // 新增：添加 Ctrl+Meta 作为多选
            boxSelectSelector: 'node:not([isZone])',
            selectableElements: 'node:not([isZone]), edge',

            style: [
                // 设备节点样式（有图标）
                {
                    selector: 'node[icon]',
                    style: {
                        'shape': 'ellipse',
                        'background-image': 'data(icon)',
                        'background-fit': 'contain',
                        'background-clip': 'none',
                        'background-color': 'transparent',
                        'background-opacity': 0,
                        'border-width': 0,
                        'width': 'data(baseSize)',
                        'height': 'data(baseSize)',
                        'label': 'data(name)',
                        'color': '#333',
                        'font-size': 0.5,
                        'text-valign': 'bottom',
                        'text-halign': 'center',
                        'text-margin-y': 0.2,
                        'text-margin-x': 0,
                        'z-index': 20,
                    }
                },
                // 未知设备节点样式（灰色圆点）
                {
                    selector: 'node[isUnknown]',
                    style: {
                        'shape': 'ellipse',
                        'width': 'data(baseSize)',
                        'height': 'data(baseSize)',
                        'background-color': '#9ca3af',
                        'label': 'data(name)',
                        'color': '#333',
                        'font-size': 0.5,
                        'text-valign': 'bottom',
                        'text-halign': 'center',
                        'text-margin-y': 0.2,
                        'text-margin-x': 0,
                        'z-index': 20,
                    }
                },
                // 分区父节点样式
                {
                    selector: 'node[isZone]',
                    style: {
                        'shape': 'round-rectangle',
                        // 圆角半径（3.x 用 corner-radius，数字=渲染像素；0.5 几乎不可见但符合用户预期效果）
                        'corner-radius': 0.5,
                        'background-color': '#66d6fb',
                        'background-opacity': 0.3,
                        'border-color': '#aaaaaa',
                        'border-width': 0.1,
                        'border-opacity': 0.8,
                        'width': 1,
                        'height': 1,
                        'padding': 0,
                        // 'padding-left': '2px',
                        // 'padding-right': '2px',
                        // 'compound-sizing-wrt-labels': 'exclude', 
                        'label': 'data(name)',
                        'color': 'rgb(251, 105, 105)',
                        'font-size': 1,
                        'font-weight': 'bold',
                        'text-valign': 'top',
                        'text-halign': 'center',
                        'text-margin-y': 0.3,
                        'text-margin-x': 0,
                        'z-index': 1,
                        // ========== 关键修改：禁止选中 + 允许拖动 ==========
                        // 'selectable': 'false',    // 核心：父节点无法被选中（框选/点击都不行）
                        // 'grabbable': 'true',      // 核心：保留父节点可拖动功能
                        'events': 'yes'           // 保留交互（拖动需要事件支持）
                    }
                },
                // 选中节点样式
                {
                    selector: 'node:selected',
                    style: {
                        'border-color': '#ff4d4f',
                        'border-width': 0.1,
                        'border-opacity': 1,
                        'z-index': 20
                    }
                },
                // 链路样式
                {
                    selector: 'edge',
                    style: {
                        'width': 0.1,
                        'line-color': '#666',
                        'line-opacity': 0.8,

                        'text-rotation': 'autorotate', // 自动旋转文本，保持与线段垂直
                        // 'text-margin-x': 10,
                        // 'text-margin-y': 10,
                        // 'font-size': 10,
                        // 'color': '#333',
                        'visibility': 'hidden',
                        'z-index': 10,
                    }
                },
                // 聚合合并边
                {
                    selector: 'edge[aggregateLine="true"]',
                    style: {
                        'width': 0.1,
                        'line-color': '#1890ff',
                        'target-arrow-color': '#1890ff',
                        'target-arrow-shape': 'none',
                        'curve-style': 'straight',
                        'visibility': 'visible',
                        'z-index': 10,
                    }
                },
                // 聚合悬浮按钮
                {
                    selector: 'node[aggregateBtn="true"]',
                    style: {
                        'shape': 'round-rectangle',
                        'width': 0.5,
                        'height': 0.5,
                        'background-color': 'transparent',
                        'background-opacity': 0,
                        'border-width': 0,
                        'label': 'data(label)',
                        'font-size': 0.5,
                        'font-weight': 'bold',
                        'color': '#000000',
                        'text-valign': 'center',
                        'text-halign': 'center',
                        'z-index': 10,
                        'underlay-color': 'transparent',
                        'visibility': 'visible'
                    }
                },
                // 淡化效果
                {
                    selector: '.faded',
                    style: {
                        'opacity': 0.2,
                    }
                },
                // ========== 新增：控制按住节点时的灰色框 ==========
                {
                    selector: 'node:active',
                    style: {
                        // 1. 改变大小（填充值）：
                        //    - 正值：比节点大（例如 10px）
                        //    - 负值：比节点小（例如 -2px）
                        //    由于你的节点现在是 1px，若设为 0，灰色框几乎就是 1px 小点
                        'overlay-padding': 0,

                        // 2. 改变颜色（默认是黑色 #000，带透明度）
                        'overlay-color': '#888888',

                        // 3. 控制透明度（1=完全不透明，0=完全透明）
                        //    如果你不想看到这个灰色框，直接设为 0 即可关闭
                        'overlay-opacity': 0.25,
                    }
                },
                {
                    selector: 'node[isZone]:active',  // 区域节点按住灰色框
                    style: {
                        'padding': 0,// 区域节点按住灰色框内边距
                        'overlay-color': '#888888',
                        'overlay-opacity': 0.25,
                        'corner-radius': 0.5,// 圆角半径
                    }
                },

                {
                    selector: 'edge:active',
                    style: {
                        // 1. 改变大小（填充值）：
                        //    - 正值：比节点大（例如 10px）
                        //    - 负值：比节点小（例如 -2px）
                        //    由于你的节点现在是 1px，若设为 0，灰色框几乎就是 1px 小点
                        'overlay-padding': 0,

                        // 2. 改变颜色（默认是黑色 #000，带透明度）
                        'overlay-color': '#888888',

                        // 3. 控制透明度（1=完全不透明，0=完全透明）
                        //    如果你不想看到这个灰色框，直接设为 0 即可关闭
                        'overlay-opacity': 0.25,
                    }
                },
                // 原点标记样式
                {
                    selector: 'node[isOrigin]',
                    style: {
                        'shape': 'ellipse',
                        'width': 1,               // 自定义圆点大小（像素），可根据需要调整
                        'height': 1,
                        'background-color': 'red',
                        'border-color': '#cc0000',
                        'border-width': 0,
                        // 'label': 'data(label)',   // 显示 "原点" 标签
                        // 'font-size': 8,
                        // 'color': '#333',
                        // 'text-valign': 'bottom',
                        // 'text-halign': 'center',
                        // 'text-margin-y': 3,
                        'z-index': 100,           // 置于顶层，避免被覆盖
                        // 'selectable': false,      // 不可被选中
                        // 'grabbable': false,       // 不可拖动
                        'events': 'no'            // 完全无交互（可选）
                    }
                }
            ]
        });

        // ========== 锁定布局：重新加载拓扑后保留锁定状态 ==========
        if (window.isLayoutLocked) {
            window.cy.autoungrabify(true);
        }

        // ================== 自定义动态网格 ==================
        let dynamicGridCanvas = null;

        function initDynamicGrid(cy, color) {
            const container = cy.container();
            if (container.querySelector('.cy-dynamic-grid')) return;

            const canvas = document.createElement('canvas');
            canvas.className = 'cy-dynamic-grid';
            canvas.style.position = 'absolute';
            canvas.style.top = 0;
            canvas.style.left = 0;
            canvas.style.pointerEvents = 'none';
            canvas.style.zIndex = 0;
            container.style.position = 'relative';
            container.prepend(canvas);
            canvas.style.display = 'none';

            dynamicGridCanvas = canvas;
            window.dcGridCanvas = canvas; // 暴露给导出逻辑，用于判断网格当前是否可见

            function drawGrid() {
                if (canvas.style.display === 'none') return;
                const rect = container.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                canvas.width = rect.width;
                canvas.height = rect.height;
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.beginPath();
                ctx.strokeStyle = color;
                ctx.lineWidth = 0.1;

                const zoom = cy.zoom();
                const pan = cy.pan();
                // 计算可见逻辑坐标范围
                const x1 = -pan.x / zoom;
                const y1 = -pan.y / zoom;
                const x2 = (canvas.width - pan.x) / zoom;
                const y2 = (canvas.height - pan.y) / zoom;

                const step = 1;  // 固定步长1（整数坐标）
                // 绘制垂直网格线（整数x）
                const startX = Math.ceil(x1 / step) * step;
                for (let x = startX; x <= x2; x += step) {
                    const screenX = x * zoom + pan.x;
                    if (screenX >= 0 && screenX <= canvas.width) {
                        ctx.moveTo(screenX, 0);
                        ctx.lineTo(screenX, canvas.height);
                    }
                }
                // 绘制水平网格线（整数y）
                const startY = Math.ceil(y1 / step) * step;
                for (let y = startY; y <= y2; y += step) {
                    const screenY = y * zoom + pan.y;
                    if (screenY >= 0 && screenY <= canvas.height) {
                        ctx.moveTo(0, screenY);
                        ctx.lineTo(canvas.width, screenY);
                    }
                }
                ctx.stroke();
            }

            cy.on('zoom pan resize', () => drawGrid()); // 监听缩放、平移、调整大小事件
            drawGrid();

            window.toggleDynamicGrid = function (show) {
                if (show === undefined) {
                    show = canvas.style.display !== 'none';
                }
                canvas.style.display = show ? '' : 'none';
                if (show) drawGrid();
                // 控制原点节点的显示/隐藏
                const originNode = window.cy ? window.cy.getElementById('origin_marker') : null;
                if (originNode && originNode.length) {
                    originNode.style('display', show ? 'element' : 'none');
                }
            };
        }

        initDynamicGrid(window.cy, '#000000');


        function initWheelPan(cy) {
            const container = cy.container();
            // 移除旧监听防止重复绑定
            if (container._wheelHandler) {
                container.removeEventListener('wheel', container._wheelHandler);
            }
            // 关闭原生用户滚轮缩放，允许代码缩放
            cy.userZoomingEnabled(false);
            cy.zoomingEnabled(true);

            const PAN_SPEED = 1;  // 平移速度
            const ZOOM_STEP = 2;  // 缩放步长
            const handler = function (e) {
                e.preventDefault();
                if (!container.contains(e.target)) return;

                let deltaY = e.deltaY;
                // 兼容滚动单位：行/页滚动
                if (e.deltaMode === 1) deltaY *= 16;
                else if (e.deltaMode === 2) deltaY *= container.clientHeight;

                // Ctrl / Command 缩放
                if (e.ctrlKey || e.metaKey) {
                    // console.log('Ctrl滚轮触发', e.ctrlKey, deltaY, cy.zoom());
                    // 官方正确API：渲染器坐标转换，修复 cy.project 不存在报错
                    const posArr = cy.renderer().projectIntoViewport(e.clientX, e.clientY);
                    const mouseLogicPos = { x: posArr[0], y: posArr[1] };

                    let newZoom = cy.zoom();
                    if (deltaY > 0) {
                        newZoom -= ZOOM_STEP;
                    } else {
                        newZoom += ZOOM_STEP;
                    }
                    // 限制缩放区间
                    // newZoom = Math.max(0.05, Math.min(15, newZoom));
                    // 以鼠标逻辑坐标为锚点缩放
                    cy.zoom({
                        level: newZoom,
                        position: mouseLogicPos
                    });
                    return;
                }

                // Shift + 滚轮：水平左右平移
                if (e.shiftKey) {
                    const offset = -deltaY * PAN_SPEED;
                    cy.panBy({ x: offset, y: 0 });
                    return;
                }

                // 无修饰键：单纯滚轮垂直上下平移画布
                const offset = -deltaY * PAN_SPEED;
                cy.panBy({ x: 0, y: offset });
            };

            container._wheelHandler = handler;
            container.addEventListener('wheel', handler, { passive: false });
        }

        initWheelPan(window.cy);

        // ====== 以下所有事件绑定都基于 window.cy ======
        // 节点选中事件
        window.cy.on('select', 'node', function (event) {
            const node = event.target;
            if (node.data('isZone') === true) {
                node.unselect();
                return;
            }
            const selectedNodes = window.cy.nodes(':selected').not('[isZone]').not('[aggregateBtn]').not('[isOrigin]');
            if (selectedNodes.length > 0) {
                const lastNode = selectedNodes[selectedNodes.length - 1];
                let showText;
                let sx, sy;
                if (selectedNodes.length === 1) {
                    showText = lastNode.data('name');
                    sx = Math.round(lastNode.position().x);
                    sy = Math.round(lastNode.position().y);
                } else {
                    // 多选：文本为数量，坐标传null，隐藏坐标
                    showText = `${selectedNodes.length}个设备`;
                    sx = null;
                    sy = null;
                }
                showNodeCoords(sx, sy, showText, '选中');
            }
        });


        window.cy.on('unselect', 'node', function (event) {
            const selectedNodes = window.cy.nodes(':selected').not('[isZone]').not('[aggregateBtn]').not('[isOrigin]');
            if (selectedNodes.length === 0) {
                document.getElementById('node-coords').textContent = '未选中节点';
            } else {
                const lastNode = selectedNodes[selectedNodes.length - 1];
                let showText;
                let sx, sy;
                if (selectedNodes.length === 1) {
                    showText = lastNode.data('name');
                    sx = Math.round(lastNode.position().x);
                    sy = Math.round(lastNode.position().y);
                } else {
                    showText = `${selectedNodes.length}个设备`;
                    sx = null;
                    sy = null;
                }
                showNodeCoords(sx, sy, showText, '选中');
            }
        });



        window.cy.on('click', function (event) {
            if (event.target === window.cy) {
                window.cy.nodes().unselect();
                document.getElementById('node-coords').textContent = '未选中节点';
            }
        });
        let draggingZone = false;
        let zoneFreeLock = false;

        window.cy.on('drag', 'node', function (event) {
            const node = event.target;
            if (node.data('isZone') === true) {
                draggingZone = true;
                zoneFreeLock = false;
                showNodeCoords(null, null, node.data('name'), '拖动分组中');
                return;
            }
            if (draggingZone) {
                return;
            }
            const selected = window.cy.nodes(':selected').not('[isZone]').not('[aggregateBtn]').not('[isOrigin]');
            let tipName;
            if (selected.length > 1) {
                tipName = `${selected.length}个设备`;
                showNodeCoords(null, null, tipName, '拖动中');
            } else {
                const x = Math.round(node.position().x);
                const y = Math.round(node.position().y);
                tipName = node.data('name');
                showNodeCoords(x, y, tipName, '拖动中');
            }
        });






        // const COORD_STEP = 1; 
        // const GRID_SIZE = 1;  
        // 节点拖动结束事件
        window.cy.on('dragfree', 'node', function (event) {
            const node = event.target;
            const rawX = node.position().x;
            const rawY = node.position().y;
            const x = Math.round(rawX);
            const y = Math.round(rawY);

            // 处理分区节点
            if (node.data('isZone') === true) {
                showNodeCoords(null, null, node.data('name'), '停止拖动分组');
                zoneFreeLock = true; // 开启松手锁，不让子节点覆盖
                return;
            }

            // 只要是拖动过分区、且刚松手锁定状态，子节点全部跳过刷新状态栏
            if (draggingZone && zoneFreeLock) {
                // 最后一个子节点执行完后，重置所有锁
                // 利用cytoscape事件同步执行特性，所有回调走完再恢复
                setTimeout(() => {
                    draggingZone = false;
                    zoneFreeLock = false;
                }, 0);
                return;
            }

            // 普通设备逻辑
            const selected = window.cy.nodes(':selected').not('[isZone]').not('[aggregateBtn]').not('[isOrigin]');
            let tipName;
            if (selected.length > 1) {
                tipName = `${selected.length}个设备`;
                showNodeCoords(null, null, tipName, '停止拖动');
            } else {
                tipName = node.data('name');
                showNodeCoords(x, y, tipName, '停止拖动');
            }

            node.position({ x: x, y: y });
            if (typeof updateAllParentZones === 'function') {
                updateAllParentZones();
            }
            if (typeof updateAggregateBtnPositions === 'function') {
                updateAggregateBtnPositions();
            }
        });





        // 提示框逻辑
        const tooltip = document.getElementById('node-tooltip');
        const cyContainer = document.getElementById('cy');

        window.cy.on('mouseover', 'node', function (event) {
            const node = event.target;
            if (node.data('isZone') || node.data('aggregateBtn')) return;
            const data = node.data();
            const connectedEdges = node.connectedEdges();
            const connectedNodes = node.connectedNodes().add(node);
            window.cy.nodes().not(connectedNodes).not('[isZone]').addClass('faded');
            window.cy.edges().not(connectedEdges).addClass('faded');

            const renderedPos = node.renderedPosition();
            const containerRect = cyContainer.getBoundingClientRect();
            let x = containerRect.left + renderedPos.x + 20;
            let y = containerRect.top + renderedPos.y + 10;

            const nodeX = Math.round(node.position().x);
            const nodeY = Math.round(node.position().y);

            tooltip.innerHTML = `
                <div class="tooltip-title">${data.name || '未知设备'}</div>
                <div class="tooltip-row">
                    <span class="tooltip-label">厂商：</span>${data.vendor || '未知'}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">类型：</span>${data.type || '未知'}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">型号：</span>${data.model || '未知'}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">IP：</span>${data.ip || '未知'}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">MAC：</span>${data.mac || '未知'}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">SN：</span>${data.sn || '未知'}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">数据中心：</span>${data.data_center || '未知'}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">坐标：</span>(${nodeX}, ${nodeY})
                </div>
            `;

            const tooltipRect = tooltip.getBoundingClientRect();
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            if (x + tooltipRect.width > viewportWidth) {
                x = containerRect.left + renderedPos.x - tooltipRect.width - 20;
            }
            if (y + tooltipRect.height > viewportHeight) {
                y = containerRect.top + renderedPos.y - tooltipRect.height - 10;
            }
            tooltip.style.left = `${x}px`;
            tooltip.style.top = `${y}px`;
            tooltip.style.opacity = 1;
        });

        window.cy.on('mouseout', 'node', function (event) {
            const node = event.target;
            if (node.data('isZone') || node.data('aggregateBtn')) return;
            window.cy.nodes().removeClass('faded');
            window.cy.edges().removeClass('faded');
            tooltip.style.opacity = 0;
        });

        window.cy.on('mouseover', 'edge', function (event) {
            const edge = event.target;
            const data = edge.data();
            const sourceNode = edge.source();
            const targetNode = edge.target();
            const highlightElements = edge.add(sourceNode).add(targetNode);
            window.cy.nodes().not(highlightElements).not('[isZone]').addClass('faded');
            window.cy.edges().not(highlightElements).addClass('faded');

            const position = event.originalEvent;
            const x = position.pageX + 10;
            const y = position.pageY + 10;

            tooltip.innerHTML = `
                <div class="tooltip-title">链路</div>
                <div class="tooltip-row">
                    <span class="tooltip-label">本端设备：</span>${sourceNode.data('name') || data.source}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">本端接口：</span>${data.aggregateLine ? '请展开查看详情' : (data.local_intf || '未知')}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">远端设备：</span>${targetNode.data('name') || data.target}
                </div>
                <div class="tooltip-row">
                    <span class="tooltip-label">远端接口：</span>${data.aggregateLine ? '请展开查看详情' : (data.remote_intf || '未知')}
                </div>
            `;
            tooltip.style.left = `${x}px`;
            tooltip.style.top = `${y}px`;
            tooltip.style.opacity = 1;
        });

        window.cy.on('mouseout', 'edge', function () {
            window.cy.nodes().removeClass('faded');
            window.cy.edges().removeClass('faded');
            tooltip.style.opacity = 0;
        });

        window.cy.on('dblclick', 'node', function (evt) {
            if (window.isLayoutLocked) return;  // 锁定状态下禁止通过双击修改坐标（防拓扑被改）
            const node = evt.target;
            if (node.data('isZone') || node.data('aggregateBtn')) return;
            const oldX = Math.round(node.position().x);
            const oldY = Math.round(node.position().y);
            let newX = prompt(`请输入节点 ${node.data('name')} 的新 X 坐标 (当前 ${oldX}):`, oldX);
            if (newX === null) return;
            let newY = prompt(`请输入节点的新 Y 坐标 (当前 ${oldY}):`, oldY);
            if (newY === null) return;
            newX = Math.round(parseFloat(newX));
            newY = Math.round(parseFloat(newY));
            if (isNaN(newX) || isNaN(newY)) {
                alert('坐标必须是数字');
                return;
            }
            node.position({ x: newX, y: newY });
        });
    }

    // ====== 改动点2：封装加载拓扑数据的函数 ======
    function loadTopology() {
        window.dcTopoLoading = true;
        // 1. 重新初始化 cytoscape（如果已有实例，initCytoscape 内部会销毁重建）
        initCytoscape();

        // 2. 获取数据并渲染
        fetch('/topology/get_dc_topology_data')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const formattedConnections = data.links.map(conn => ({
                        group: 'edges',
                        data: conn
                    }));
                    createTopologyNodes(data.nodes, formattedConnections);
                    updateDeviceList(data.nodes);
                    mergeMultipleEdges();
                    window.dcTopoLoading = false;
                } else {
                    window.dcTopoLoading = false;
                    alert('获取拓扑数据失败: ' + data.error);
                }
            })
            .catch(error => { window.dcTopoLoading = false; console.error('加载拓扑请求失败:', error); });
    }

    // ====== 节点创建函数（内部使用 window.cy） ======
    function createTopologyNodes(devices, connections) {
        console.debug(`实际设备数量: ${devices.length}`);
        console.debug(`实际链路数量: ${connections.length}`);

        const hasCoordinates = devices.some(device =>
            device.x !== null && device.x !== undefined &&
            device.y !== null && device.y !== undefined &&
            !isNaN(device.x) && !isNaN(device.y)
        );

        const deviceNodes = devices
            .filter(device => device.id && device.name)
            .map(device => {
                if (!device.type || device.type === '未知') {
                    device.type = '未知';
                }
                const config = deviceTypeConfig[device.type];
                // const baseSize = device.size ? device.size * 0.5 : 30;
                // const hoverSize = device.size ? device.size * 0.7 : 40;
                const baseSize = 1;
                const hoverSize = 1;
                const nodeData = {
                    id: device.id,
                    name: device.name,
                    vendor: device.vendor,
                    model: device.model,
                    ip: device.ip,
                    data_center: device.data_center,
                    area: device.area,
                    type: device.type,
                    color: config.color,
                    baseSize: baseSize,
                    hoverSize: hoverSize
                };
                if (device.type === '未知') {
                    nodeData.isUnknown = true;
                } else {
                    nodeData.icon = config.icon;
                }
                const node = { group: 'nodes', data: nodeData };
                if (hasCoordinates) {
                    node.position = {
                        x: Math.round(device.x),
                        y: Math.round(device.y)
                    };
                }
                return node;
            });

        const areaMap = new Map();
        deviceNodes.forEach(node => {
            const rawArea = node.data.area;
            if (rawArea && typeof rawArea === 'string') {
                const cleaned = rawArea.trim().replace(/\s+/g, '_');
                if (cleaned) {
                    areaMap.set(rawArea, cleaned);
                    node.data.area = cleaned;
                }
            }
        });
        const zoneSet = new Set(areaMap.values());

        const zoneNodes = [];
        zoneSet.forEach(cleaned => {
            const originalName = [...areaMap.entries()].find(([raw, cl]) => cl === cleaned)?.[0] || cleaned;
            zoneNodes.push({
                group: 'nodes',
                data: {
                    id: `zone_${cleaned}`,
                    name: originalName,
                    isZone: true,
                    selectable: false, // 不可被选中
                    grabbable: true   // 可拖动
                },
                position: { x: 0, y: 0 }
            });
        });

        deviceNodes.forEach(node => {
            const area = node.data.area;
            if (area && zoneSet.has(area)) {
                node.data.parent = `zone_${area}`;
            }
        });

        window.cy.add([...zoneNodes, ...deviceNodes, ...connections]);

        function updateAllParentZones() {
            zoneSet.forEach(cleaned => {
                const parentId = `zone_${cleaned}`;
                const parentNode = window.cy.getElementById(parentId);
                if (parentNode.length === 0) return;
                const children = parentNode.children();
                if (children.length === 0) {
                    parentNode.remove();
                    return;
                }
                let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
                children.forEach(child => {
                    const bb = child.boundingBox();
                    minX = Math.min(minX, bb.x1);
                    maxX = Math.max(maxX, bb.x2);
                    minY = Math.min(minY, bb.y1);
                    maxY = Math.max(maxY, bb.y2);
                    // const w = child.width();
                    // const h = child.height();
                    // const x = child.position('x');
                    // const y = child.position('y');
                    // minX = Math.min(minX, x - w / 2);
                    // maxX = Math.max(maxX, x + w / 2);
                    // minY = Math.min(minY, y - h / 2);
                    // maxY = Math.max(maxY, y + h / 2);
                });


                const width = Math.round(maxX - minX);
                const height = Math.round(maxY - minY);
                const centerX = Math.round((minX + maxX) / 2);
                const centerY = Math.round((minY + maxY) / 2);
                parentNode.style({ 'width': width, 'height': height });
                parentNode.position({ x: centerX, y: centerY });
            });
        }

        // 添加原点标记（红色圆点，固定在 (0,0)）
        function addOriginMarker() {
            const originId = 'origin_marker';
            // 避免重复添加
            if (window.cy.getElementById(originId).length === 0) {
                window.cy.add({
                    group: 'nodes',
                    data: {
                        id: originId,
                        isOrigin: true,
                        // label: '原点',
                        selectable: false, // 不可被选中
                        grabbable: false   // 不可拖动
                    },
                    position: { x: 0, y: 0 }
                });
                // 默认隐藏（因为网格默认不显示）
                const node = window.cy.getElementById(originId);
                if (node.length) {
                    node.style('display', 'none');
                }
            }
        }

        function clusterChildrenByZone(cy, shrinkFactor = 0.5) {
            // 遍历所有分区父节点
            cy.nodes('[isZone]').forEach(parent => {
                const children = parent.children().filter(node => !node.data('isZone'));
                if (children.length < 2) return; // 少于2个无需聚类

                // 计算当前子节点的中心
                let cx = 0, cyPos = 0;
                children.forEach(child => {
                    const pos = child.position();
                    cx += pos.x;
                    cyPos += pos.y;
                });
                cx /= children.length;
                cyPos /= children.length;

                // 将每个子节点向中心收缩
                children.forEach(child => {
                    const pos = child.position();
                    const dx = pos.x - cx;
                    const dy = pos.y - cyPos;
                    // 收缩系数 shrinkFactor，0.5 表示向中心移动一半距离
                    child.position({
                        x: cx + dx * shrinkFactor,
                        y: cyPos + dy * shrinkFactor
                    });
                });

                // 收缩后，父节点范围会自动更新（您已有 updateAllParentZones）
            });
        }



        if (hasCoordinates) {
            window.cy.layout({ name: 'preset' }).run();
        } else {
            window.cy.layout({
                name: 'breadthfirst',
                directed: true,
                avoidOverlap: true,// 避免节点重叠
                padding: 0,
                // fit: true,                                  // 关键
                boundingBox: { x1: -30, y1: -20, w: 60, h: 40 },  // boundingBox是布局区域，确保所有节点都在这个区域内
                spacingFactor: 1,// 节点间距
            }).run();
            // ---- 新增：聚类子节点 ----
            clusterChildrenByZone(window.cy, 0.4);  // 0.4 表示适度收缩
            window.cy.nodes().not('[isZone]').forEach(node => {
                const x = Math.round(node.position().x);
                const y = Math.round(node.position().y);
                node.position({ x: x, y: y });
            });
        }

        addOriginMarker();
        // updateAllParentZones();
    }

    // 更新设备列表
    function updateDeviceList(devices) {
        const deviceList = document.getElementById('device-list');
        deviceList.innerHTML = '';
        devices.forEach(device => {
            const deviceItem = document.createElement('div');
            deviceItem.className = 'p-2 border rounded hover:bg-gray-100 cursor-pointer transition-colors';
            deviceItem.innerHTML = `
                <div class="text-xs ">${device.name}</div>
                <div class="text-xs text-gray-600">${device.vendor || '未知厂商'} | ${device.model || '未知型号'}</div>
            `;
            deviceItem.addEventListener('click', () => {
                const targetNode = window.cy.nodes(`[id="${device.id}"]`);
                if (targetNode.length > 0) {
                    window.cy.nodes().unselect();
                    targetNode.select();
                    // 等首帧渲染完成后再设视口，避免被首次 draw 覆盖导致“第一次点击不跳转”
                    // 用 animate 把居中+缩放合并成一次原子视口更新，规避 center/zoom 时序竞态
                    window.cy.ready(() => {
                        window.cy.animate(
                            { center: { eles: targetNode }, zoom: 25 },
                            { duration: 150 }
                        );
                    });
                    const x = Math.round(device.x || targetNode.position().x);
                    const y = Math.round(device.y || targetNode.position().y);
                    showNodeCoords(x, y, device.name);
                }
            });
            deviceList.appendChild(deviceItem);
        });
    }

    function showNodeCoords(x, y, deviceName, status = '选中') {
        // 多选/拖动分组时坐标传 null/undefined，统一显示为 —
        const intX = (x === null || x === undefined) ? '—' : Math.round(x);
        const intY = (y === null || y === undefined) ? '—' : Math.round(y);
        document.getElementById('node-coords').textContent = `${status} - ${deviceName} - X: ${intX}, Y: ${intY}`;
    }

    // ====== 以下函数内部使用 window.cy ======



    // 聚合边管理
    let aggregateMap = {};

    function mergeMultipleEdges() {
        aggregateMap = {};
        window.cy.remove('node[aggregateBtn="true"]');
        window.cy.remove('edge[aggregateLine="true"]');

        const edgeGroups = {};
        window.cy.edges().forEach(edge => {
            const source = edge.source().id();
            const target = edge.target().id();
            const groupKey = [source, target].sort().join('_');
            edgeGroups[groupKey] ||= [];
            edgeGroups[groupKey].push(edge);
        });

        Object.values(edgeGroups).forEach(edgeList => {
            if (edgeList.length < 2) {
                edgeList.forEach(e => {
                    // 单条边恢复默认直线样式，避免残留曲线样式
                    e.style({
                        'curve-style': 'straight',
                        'visibility': 'visible'
                    });
                });
                return;
            }
            const firstEdge = edgeList[0];
            const sourceId = firstEdge.source().id();
            const targetId = firstEdge.target().id();
            const key = [sourceId, targetId].sort().join('_');
            const aggregateLine = window.cy.add({
                group: 'edges',
                data: {
                    id: `agg_line_${key}`,
                    source: sourceId,
                    target: targetId,
                    aggregateLine: 'true'
                }
            });
            const sourceNode = firstEdge.source();
            const targetNode = firstEdge.target();
            const midX = (sourceNode.position().x + targetNode.position().x) / 2;
            const midY = (sourceNode.position().y + targetNode.position().y) / 2;
            const aggregateBtn = window.cy.add({
                group: 'nodes',
                data: {
                    id: `agg_btn_${key}`,
                    aggregateBtn: 'true',
                    label: `+ ${edgeList.length}`
                },
                position: { x: midX, y: midY }
            });
            aggregateMap[aggregateBtn.id()] = {
                line: aggregateLine,
                edges: edgeList
            };

            // 给每条并行边设置对称偏移的贝塞尔曲线，展开后自动错开不重合
            const edgeCount = edgeList.length;
            edgeList.forEach((edge, index) => {
                // 以组中间为原点，向两侧对称分布偏移量
                const offset = (index - (edgeCount - 1) / 2) * 1;
                edge.style({
                    'curve-style': 'unbundled-bezier',
                    'control-point-distances': [offset],
                    'control-point-weights': [0.5],
                    'visibility': 'hidden'
                });
                edge.data('merged', 'true');
            });
        });


        bindToggleEvent();

        function updateAggregateBtnPositions() {
            Object.keys(aggregateMap).forEach(btnId => {
                const { edges } = aggregateMap[btnId];
                const edge = edges[0];
                const sourceNode = edge.source();
                const targetNode = edge.target();
                const midX = (sourceNode.position().x + targetNode.position().x) / 2;
                const midY = (sourceNode.position().y + targetNode.position().y) / 2;
                const btnNode = window.cy.getElementById(btnId);
                if (btnNode.length) {
                    btnNode.position({ x: midX, y: midY });
                }
            });
        }

        updateAggregateBtnPositions();
        window.cy.off('drag', 'node', updateAggregateBtnPositions);
        window.cy.off('dragfree', 'node', updateAggregateBtnPositions);
        window.cy.on('drag', 'node', updateAggregateBtnPositions);
        window.cy.on('dragfree', 'node', updateAggregateBtnPositions);
    }

    function bindToggleEvent() {
        window.cy.off('click', 'node[aggregateBtn="true"]');
        window.cy.on('click', 'node[aggregateBtn="true"]', evt => {
            const btn = evt.target;
            const data = aggregateMap[btn.id()];
            if (!data) return;
            const { line, edges } = data;
            const isMerged = edges[0].data('merged') === 'true';
            if (isMerged) {
                line.style('visibility', 'hidden');
                edges.forEach(edge => {
                    edge.data('merged', 'false');
                    edge.style('visibility', 'visible');
                });
                btn.data('label', `- ${edges.length}`);
            } else {
                line.style('visibility', 'visible');
                edges.forEach(edge => {
                    edge.data('merged', 'true');
                    edge.style('visibility', 'hidden');
                });
                btn.data('label', `+ ${edges.length}`);
            }
        });
    }

    // 网格开关
    const toggleGridBtn = document.getElementById('toggleGridBtn');
    if (toggleGridBtn) {
        let gridVisible = false;
        toggleGridBtn.addEventListener('click', () => {
            gridVisible = !gridVisible;
            if (typeof window.toggleDynamicGrid === 'function') {
                window.toggleDynamicGrid(gridVisible);
            }
            toggleGridBtn.textContent = gridVisible ? '隐藏网格' : '显示网格';
        });
    }


    // ====== 锁定 / 解锁布局 ======

    // 应用锁定状态：
    //   locked=true  → autoungrabify(true) 禁止用户拖动任何节点/父节点
    //   locked=false → autoungrabify(false) 恢复节点/父节点的可拖动能力
    // 注意：锁定只影响“用户拖拽”，不影响鼠标悬浮 tooltip 的展示
    function applyLayoutLock(locked) {
        if (!window.cy) return;
        window.cy.autoungrabify(locked);
        window.isLayoutLocked = locked;
    }

    const lockLayoutBtn = document.getElementById('lockLayoutBtn');
    if (lockLayoutBtn) {
        lockLayoutBtn.addEventListener('click', () => {
            const locked = !window.isLayoutLocked;
            applyLayoutLock(locked);

            const span = lockLayoutBtn.querySelector('span') || lockLayoutBtn;
            if (locked) {
                // 进入锁定：禁用拖动，仅保留查看
                span.textContent = '解锁布局';
                showToast('布局已锁定：节点不可拖动，仅可查看 tooltip 信息', 'success');
            } else {
                // 解除锁定：恢复可调整拓扑
                span.textContent = '锁定布局';
                showToast('布局已解锁：可重新拖动并调整拓扑', 'success');
            }
        });
    }





    // 保存拓扑
    document.getElementById('save-topology').addEventListener('click', function () {
        const btn = this;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span>保存中...</span>';
        btn.disabled = true;
        const nodes = window.cy.nodes()
            .filter(node => !node.data('isZone') && !node.data('aggregateBtn') && !node.data('isOrigin'))
            .map(node => ({
                id: node.id(),
                name: node.data('name'),
                x: Math.round(node.position().x),
                y: Math.round(node.position().y)
            }));
        fetch_save_dc = '/topology/save_dc_topology'
        fetch(fetch_save_dc, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ devices: nodes })
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.not_found.length > 0) {
                        alert(`坐标表的"总拓扑"分区中未找到以下设备（共${data.not_found.length}个），请添加后重新保存:\n${data.not_found.join('\n')}`);
                        showToast('部分拓扑保存成功，请检查后重新保存', 'success');
                    } else {
                        showToast('拓扑保存成功', 'success');
                    }
                } else {
                    showToast('请关闭表格后重试: ' + data.error, 'error');
                }
            })
            .catch(error => {
                showToast('请检查前后端路由是否正确:' + fetch_save_dc, 'error');
            })
            .finally(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            });
    });

    // PNG导出
    // 方案A：导出「当前视口」，并直接复用画布上已有的网格 canvas（1:1 叠加，绝不重画）
    document.getElementById('exportPngBtn').addEventListener('click', async (event) => {
        const btn = event.currentTarget;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span>导出中...</span>';
        btn.disabled = true;
        try {
            const cy = window.cy;
            if (!cy) {
                showToast('图表未就绪', 'error');
                return;
            }

            // 必须在拓扑页面且生成/加载完成才能导出，避免导出损坏/空白图
            const dcContainer = cy.container();
            if (window.dcTopoLoading) {
                showToast('拓扑生成/加载中，请稍后再导出', 'error');
                return;
            }
            if (!dcContainer || dcContainer.style.display === 'none' || dcContainer.offsetWidth === 0) {
                showToast('拓扑尚未显示，无法导出', 'error');
                return;
            }

            // 导出前：隐藏“原点”控件节点（非拓扑数据）；隐藏 tooltip；清空选中（去掉红圈）
            // 说明：聚合按钮保留显示（用户要求）；选中与 tooltip 导出后不再恢复
            const origin = cy.getElementById('origin_marker');
            const originWasVisible = origin.length && origin.style('display') !== 'none';
            if (origin.length) origin.style('display', 'none');

            // 隐藏节点 tooltip（DOM 浮层，导出后不恢复）
            const nodeTip = document.getElementById('node-tooltip');
            if (nodeTip) nodeTip.style.opacity = '0';

            // 清空当前选中，红圈/选中边框不进入 PNG（导出后不恢复选中）
            cy.elements().unselect();

            // 清除 hover/选中产生的 .faded 高亮（高亮节点与链路），导出后不恢复
            cy.elements().removeClass('faded');

            // full:true 导出完整拓扑；scale:40 放大保证清晰度
            const baseDataUrl = cy.png({
                full: true,
                bg: 'white',
                scale: 30
            });

            // 恢复原点显示状态（网格开则显示，否则隐藏）
            if (origin.length) origin.style('display', originWasVisible ? 'element' : 'none');
            // 注：聚合按钮保留显示；选中状态与 tooltip 导出后不恢复

            // 导出 PNG 不再叠加网格，仅保留白底拓扑
            const finalDataUrl = baseDataUrl;

            // 文件名追加本地时间戳（YYYYMMDDHHMMSS）
            const d = new Date();
            const pad2 = n => String(n).padStart(2, '0');
            const ts = `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}${pad2(d.getHours())}${pad2(d.getMinutes())}${pad2(d.getSeconds())}`;

            const link = document.createElement('a');
            link.href = finalDataUrl;
            link.download = `总拓扑-${ts}.png`;
            link.click();
            URL.revokeObjectURL(link.href);
            link.remove();
            showToast('PNG 导出成功', 'success');
        } catch (e) {
            console.error('PNG导出异常：', e);
            showToast('导出失败，请重试', 'error');
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    });

    // ====== 改动点3：新增刷新按钮事件 ======
    document.getElementById('refreshTopologyBtn').addEventListener('click', function () {
        const btn = this;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span>刷新中...</span>';

        fetch('/refresh_cache', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keys: ['dc_topology_data'] })
        })
            .then(response => {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(data => {
                if (!data.success) throw new Error(data.message || '缓存刷新失败');
                // 重新加载拓扑
                loadTopology();
                showToast('拓扑数据已刷新（缓存已更新）', 'success');
            })
            .catch(error => {
                console.error('刷新失败:', error);
                showToast('刷新失败: ' + error.message, 'error');
            })
            .finally(() => {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            });
    });

});

// 窗口尺寸变化时隐藏提示框
window.addEventListener('resize', function () {
    const tooltip = document.getElementById('node-tooltip');
    if (tooltip) tooltip.style.opacity = 0;
});
