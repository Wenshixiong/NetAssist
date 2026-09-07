console.debug('延迟3秒后执行，此期间切页面不卡顿');
setTimeout(() => { }, 3000);
// ========== Toast 提示组件 ==========
function showToast(message, type = 'success') {
    // 移除已存在的 Toast（避免重叠）
    const oldToast = document.querySelector('.custom-toast');
    if (oldToast) oldToast.remove();

    // 创建 Toast 容器
    const toast = document.createElement('div');
    toast.className = 'custom-toast fixed top-4 right-4 z-50 px-6 py-3 rounded-lg shadow-lg text-white transition-all duration-300 transform translate-x-full opacity-0';

    // 根据类型设置背景色
    const colors = {
        success: 'bg-green-500',
        error: 'bg-red-500',
        warning: 'bg-yellow-500',
        info: 'bg-blue-500'
    };
    toast.classList.add(colors[type] || colors.info);

    // 图标
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    toast.innerHTML = `<i class="fa ${icons[type] || icons.info} mr-2"></i> ${message}`;

    document.body.appendChild(toast);

    // 触发进入动画
    setTimeout(() => {
        toast.classList.remove('translate-x-full', 'opacity-0');
        toast.classList.add('translate-x-0', 'opacity-100');
    }, 10);

    // 3.5秒后自动消失
    setTimeout(() => {
        toast.classList.remove('translate-x-0', 'opacity-100');
        toast.classList.add('translate-x-full', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}


// 全局变量
let deviceModelChart;          // 图表实例
let selectedModels = [];       // 选中的型号列表
let selectedFenqu = [];
let modelList = [];            // 型号列表（改为空数组，通过Fetch赋值）
let abortController = null;  // 在页面离开时取消所有请求
document.addEventListener('DOMContentLoaded', async function () {

    // 取消之前的请求（如果存在）
    if (abortController) {
        abortController.abort();
    }
    abortController = new AbortController();
    const signal = abortController.signal;



    // ===============================
    // 初始化数据中心图表
    const dataCenterChart = echarts.init(document.getElementById('data-center-chart'));

    // 数据中心饼图配置
    const dataCenterOption = {
        tooltip: {
            trigger: 'item',
            formatter: '{a} <br/>{b}: {c}台 ({d}%)'
        },
        legend: {
            orient: 'vertical',
            left: 10,
            top: 'bottom',
            data: [] // 由后端数据填充
        },
        series: [
            {
                name: '数据中心',
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: true,
                itemStyle: {
                    borderRadius: 10,
                    borderColor: '#fff',
                    borderWidth: 2
                },
                label: {
                    show: true,
                    position: 'outside',
                    formatter: '{b}: {c}台 ({d}%)',
                    fontSize: 12
                },
                labelLine: {
                    show: true,
                    length: 15,
                    length2: 20,
                    lineStyle: {
                        width: 1
                    }
                },
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 16,
                        fontWeight: 'bold'
                    }
                },
                data: []
            }
        ],
        color: ['#8b5cf6', '#ec4899', '#f97316', '#06b6d4', '#14b8a6'] // 紫色系配色
    };

    // 设置初始图表配置
    dataCenterChart.setOption(dataCenterOption);

    // 从后端获取数据并更新图表
    function fetchDataCenterData() {

        return fetch('/dc_status', { signal })
            .then(response => {
                // 处理HTTP状态码异常
                if (!response.ok) {
                    throw new Error(`接口请求失败：${response.status} ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.debug('获取到的数据中心数据：', data);

                // 1. 处理后端错误返回（如文件不存在）
                if (data.error) {
                    alert(`数据加载失败：${data.error}`);
                    return;
                }

                // 2. 将后端返回的扁平数据转换为ECharts所需格式（动态解析所有非total字段）
                const chartData = [];
                for (const key in data) {
                    if (key !== 'total') {
                        chartData.push({
                            name: key,
                            value: data[key]
                        });
                    }
                }

                // 3. 过滤掉数值为0的项（可选，根据需求调整）
                const validChartData = chartData.filter(item => item.value > 0);

                // 4. 更新图表配置（假设 dataCenterChart 已初始化为 ECharts 实例）
                dataCenterChart.setOption({
                    series: [{
                        data: validChartData
                    }],
                    legend: {
                        data: validChartData.map(item => item.name)
                    }
                });

                // 5. 更新页面统计信息
                if (document.getElementById('dc-total-devices')) {
                    document.getElementById('dc-total-devices').textContent = data.total || 0;
                }
                // 更新数据中心数量（显示实际存在的数据中心个数）
                if (document.getElementById('dc-total-class')) {
                    document.getElementById('dc-total-class').textContent = validChartData.length;
                }
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    console.debug('请求被取消（页面切换）:', error.message);
                    return; // 静默忽略，不执行任何 UI 更新
                }
                console.error('获取数据中心数据失败:', error);
                // alert('数据加载失败，请检查后端服务是否启动！');
                // 清空图表数据，避免残留
                dataCenterChart.setOption({
                    series: [{ data: [] }],
                    legend: { data: [] }
                });
            });
    }

    // 初始加载数据
    fetchDataCenterData();

    // 初始化EOS饼图
    const EOSChart = echarts.init(document.getElementById('device-eos-chart'));

    // 配置图表样式
    const EOSOption = {
        tooltip: {
            trigger: 'item',
            formatter: '{a} <br/>{b}: {c}台 ({d}%)'
        },
        legend: {
            orient: 'vertical',
            left: 10,
            top: 'bottom',
            data: ['服务停止', '即将停止', '无EOS信息', '服务中'], // 明确指定图例顺序
            // 格式化图例文本：给"即将停止"添加备注
            formatter: function (name) {
                return name === '即将停止' ? '即将停止(未来2年)' : name;
            }
        },
        series: [
            {
                name: 'EOS状态',
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: true,
                itemStyle: {
                    borderRadius: 10,
                    borderColor: '#fff',
                    borderWidth: 2
                },
                // 新增标签配置：显示名称、数值和百分比
                label: {
                    show: true,
                    position: 'outside', // 标签显示在外侧
                    formatter: '{b}: {c}台 ({d}%)', // 格式：名称: 数量(百分比)
                    fontSize: 12
                },
                // 显示标签连接线
                labelLine: {
                    show: true,
                    length: 15, // 第一段线长度
                    length2: 20, // 第二段线长度
                    lineStyle: {
                        width: 1 // 线宽
                    }
                },
                // 鼠标高亮
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 16,
                        fontWeight: 'bold'
                    }
                },
            }
        ],
        color: [
            '#ef4444', // 服务停止   红色
            '#f59e0b', // 即将停止 黄色=
            '#6b7280', // 无EOS信息   灰色=
            '#10b981', // 服务中   绿色
        ]
    };

    // 设置图表配置
    EOSChart.setOption(EOSOption);

    // EOS设备数据加载 =
    function fetchEOSData() {
        return fetch('/eos_status', { signal })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`接口请求失败：${response.status} ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.debug('获取到的EOS数据：', data);
                // 处理后端错误信息
                if (data.error) {
                    alert(`数据加载失败啊：${data.error}`);
                    return;
                }

                // 直接使用后端的明细数据，转换为ECharts格式
                const chartData = data.data.map(item => ({
                    name: item.status,
                    value: item.count
                }));

                // 更新图表配置
                EOSChart.setOption({
                    series: [{ data: chartData }]
                });

                // 设备数量统计
                document.getElementById('eos-total-devices').textContent = data.total_device || 0;
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    console.debug('EOS请求被取消:', error.message);
                    return;
                }
                console.error('获取厂商设备数据失败:', error);
                // alert('数据加载失败，请检查后端服务是否启动！');
            });
    }
    // Excel导出功能 下载维保Excel
    document.getElementById('export-eos-btn').addEventListener('click', function () {
        downloadFile('/export_eos_excel', this, '设备EOS统计.xlsx');
    });
    // 初始加载数据
    fetchEOSData();

    // ===============================
    const ManufacturerChart = echarts.init(document.getElementById('manufacturer-chart'));

    // 基于厂商名生成固定随机色（刷新不变化）
    function getFixedColorByManufacturer(name) {
        // 计算字符串哈希值
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            hash = name.charCodeAt(i) + ((hash << 5) - hash);
        }
        // 转换为RGB
        const r = (hash & 0xFF0000) >> 16;
        const g = (hash & 0x00FF00) >> 8;
        const b = hash & 0x0000FF;
        // 保证颜色亮度
        const adjust = (v) => Math.min(255, Math.max(55, v));
        return `#${adjust(r).toString(16).padStart(2, '0')}${adjust(g).toString(16).padStart(2, '0')}${adjust(b).toString(16).padStart(2, '0')}`;
    }

    // 配置图表样式
    const ManufacturerOption = {
        tooltip: {
            trigger: 'item',
            formatter: '{a} <br/>{b}: {c}台 ({d}%)'
        },
        legend: {
            orient: 'vertical',
            left: 10,
            top: 'bottom',
        },
        series: [
            {
                name: '厂商',
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: true,
                itemStyle: {
                    borderRadius: 10,
                    borderColor: '#fff',
                    borderWidth: 2
                },
                // 新增标签配置：显示名称、数值和百分比
                label: {
                    show: true,
                    position: 'outside', // 标签显示在外侧
                    formatter: '{b}: {c}台 ({d}%)', // 格式：名称: 数量(百分比)
                    fontSize: 12
                },
                // 显示标签连接线
                labelLine: {
                    show: true,
                    length: 15, // 第一段线长度
                    length2: 20, // 第二段线长度
                    lineStyle: {
                        width: 1 // 线宽
                    }
                },
                // 鼠标高亮
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 16,
                        fontWeight: 'bold'
                    }
                },
                data: []
            }
        ],

    };

    // 设置图表配置
    ManufacturerChart.setOption(ManufacturerOption);

    // 厂商设备数据加载 =
    function fetchManufacturerData() {
        return fetch('/manufacturer_status', { signal })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`接口请求失败：${response.status} ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.debug('获取到的厂商设备数据：', data);
                // 处理后端错误信息
                if (data.error) {
                    alert(`数据加载失败啊：${data.error}`);
                    return;
                }

                // 直接使用后端的明细数据，转换为ECharts格式
                const chartData = data.data.map(item => ({
                    name: item.manufacturer,
                    value: item.total_count  // 直接复用后端计算的数量
                }));

                // 基于厂商名生成固定颜色
                const fixedColors = data.data.map(item => getFixedColorByManufacturer(item.manufacturer));

                // 更新图表配置
                ManufacturerChart.setOption({
                    color: fixedColors,  // 动态分配的颜色
                    series: [{ data: chartData }]
                });

                // 设备数量统计
                document.getElementById('manufacturer-total-devices').textContent = data.total_device || 0;
                // 厂商数量统计项
                document.getElementById('manufacturer-total-class').textContent = data.total_manufacturer || 0;
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    console.debug('厂商请求被取消:', error.message);
                    return;
                }
                console.error('获取厂商设备数据失败:', error);
                // alert('数据加载失败，请检查后端服务是否启动！');
            });
    }

    // 初始加载数据
    fetchManufacturerData();




    // ===============================
    // 初始化维保状态图表 ECharts实例
    const serviceStatusChart = echarts.init(document.getElementById('service-status-chart'));

    // 配置图表样式
    const ServiceStatusOption = {
        tooltip: {
            trigger: 'item',
            formatter: '{a} <br/>{b}: {c}台 ({d}%)'
        },
        legend: {
            orient: 'vertical',
            left: 10,
            top: 'bottom',
            data: ['无维保信息', '已过保', '未过保', '即将过保'], // 明确指定图例顺序
            // 格式化图例文本：给"即将停止"添加备注
            formatter: function (name) {
                return name === '即将过保' ? '即将过保(未来半年)' : name;
            }
        },
        series: [
            {
                name: '维保状态',
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: true,
                itemStyle: {
                    borderRadius: 10,
                    borderColor: '#fff',
                    borderWidth: 2
                },
                // 新增标签配置：显示名称、数值和百分比
                label: {
                    show: true,
                    position: 'outside', // 标签显示在外侧
                    formatter: '{b}: {c}台 ({d}%)', // 格式：名称: 数量(百分比)
                    fontSize: 12
                },
                // 显示标签连接线
                labelLine: {
                    show: true,
                    length: 15, // 第一段线长度
                    length2: 20, // 第二段线长度
                    lineStyle: {
                        width: 1 // 线宽
                    }
                },
                // 鼠标高亮
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 16,
                        fontWeight: 'bold'
                    }
                },
                data: []
            }
        ],
        color: [
            '#6b7280', // 无维保   灰色
            '#ef4444', // 已过保   红色
            '#10b981', // 未过保   绿色
            '#f59e0b', // 即将过保 黄色
        ]
    };

    // 设置图表配置
    serviceStatusChart.setOption(ServiceStatusOption);

    // 维保数据加载 =
    function fetchServiceStatusData() {
        return fetch('maintenance_status', { signal })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`接口请求失败：${response.status} ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.debug('获取到的维保数据：', data);
                if (data.success) {
                    serviceStatusChart.setOption({
                        series: [{ data: data.data }]
                    });
                    if (document.getElementById('service-total-devices')) {
                        document.getElementById('service-total-devices').textContent = data.total || 0;
                    }
                } else {
                    alert(`数据加载失败：${data.error}`, 'error');
                    serviceStatusChart.setOption({ series: [{ data: [] }] });
                }
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    console.debug('维保请求被取消:', error.message);
                    return;
                }
                console.error('获取维保状态数据失败:', error);
                // alert('维保数据加载失败，请检查后端服务！', 'error');
                serviceStatusChart.setOption({ series: [{ data: [] }] });
                document.getElementById('service-total-devices').textContent = 0;
            });
    }

    // Excel导出功能 下载维保Excel
    document.getElementById('export-service-btn').addEventListener('click', function () {
        downloadFile('/export_maintenance_excel', this, '设备维保统计.xlsx');
    });

    // 初始加载数据
    fetchServiceStatusData();

    // ===============================
    // 刷新缓存按钮事件
    document.getElementById('refresh-btn').addEventListener('click', function () {
        const btn = this;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> 刷新缓存中...';

        // 信息图表依赖的缓存键列表
        const cacheKeys = [
            'dc_status',
            'maintenance_status',
            'eos_status',
            'manufacturer_status',
            'device_model_list',
            'business_zone_list',
            'device_model_count',
            'business_zone_count'
        ];

        fetch('/refresh_cache', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keys: cacheKeys })
        })
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(data => {
                if (!data.success) throw new Error(data.message || '缓存刷新失败');
                btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> 重新加载数据...';
                return Promise.all([
                    fetchServiceStatusData(),
                    fetchDeviceModelData(selectedModels),
                    fetchNetworkPartitionData(selectedFenqu),
                    fetchDataCenterData(),
                    fetchManufacturerData(),
                    fetchEOSData()
                ]);
            })
            .then(() => {
                showToast('信息图表数据刷新完成（缓存已更新）', 'success');
                btn.disabled = false;
                btn.innerHTML = '<i class="fa fa-sync-alt"></i> 再次刷新数据';
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa fa-sync-alt"></i> 再次刷新数据';
                    return;
                }
                console.error('刷新失败:', error);
                showToast('刷新失败: ' + (error.message || '未知错误'), 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="fa fa-sync-alt"></i> 刷新失败，请重试';
            });
    });

    // 响应窗口大小变化
    window.addEventListener('resize', function () {
        serviceStatusChart.resize();
        // deviceModelChart.resize();
        // networkPartitionChart.resize();
        dataCenterChart.resize();
        ManufacturerChart.resize();
        EOSChart.resize();
    });



    // ====================================================================================

    // 1. 初始化图表实例（设备型号分布、网络分区分布）
    initDeviceModelChart();
    initNetworkPartitionChart();

    // 2. 异步加载选项列表并动态生成复选框

    await loadDeviceModels();
    await loadBusinessZones();



    // 3. 绑定下拉框展开/收起交互
    initDropdownToggle('modelSelectTrigger', 'modelSelectList', 'model-down-icon');
    initDropdownToggle('fenquSelectTrigger', 'fenquSelectList', 'fenqu-down-icon');

    // 4. 初始显示全量数据（因为全选按钮初始未勾选，且复选框都可用，但默认无勾选）
    //    所以图表会显示全量数据（因为 fetchDeviceModelData([]) 表示全量）

    fetchDeviceModelData([]);
    fetchNetworkPartitionData([]);




    // ====================================================================================


    /**
     * 初始化ECharts图表（逻辑不变）
     */
    function initDeviceModelChart() {
        const chartDom = document.getElementById('device-model-chart');
        if (!chartDom) return;

        deviceModelChart = echarts.init(chartDom);
        const option = {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                formatter: '{b}：{c} 台'
            },
            grid: {
                left: '3%',
                right: '4%',
                bottom: '3%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                data: [],
                axisLabel: { fontSize: 12, rotate: 15 }
            },
            yAxis: {
                type: 'value',
                name: '设备数量（台）',
                nameTextStyle: { fontSize: 12 }
            },
            series: [{
                name: '设备数量',
                type: 'bar',
                data: [],
                barWidth: '60%',
                itemStyle: {
                    color: (params) => {
                        const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444'];
                        return colors[params.dataIndex % colors.length];
                    }
                },
                // 新增 label 配置
                label: {
                    show: true,                // 显示标签
                    position: 'top',            // 标签位置：top（柱子上方）、inside（柱子内部）等
                    color: '#333',               // 文字颜色
                    fontSize: 12,                // 文字大小
                    fontWeight: 'bold',          // 可选：加粗
                    formatter: '{c}'          // 自定义显示格式，{c} 代表数据值
                }
            }]
        };
        deviceModelChart.setOption(option);
        window.addEventListener('resize', () => deviceModelChart.resize());
    }

    function initNetworkPartitionChart() {
        const chartDom = document.getElementById('fenqu-chart');
        if (!chartDom) return;

        fenquChart = echarts.init(chartDom);
        const option = {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                formatter: '{b}：{c} 台'
            },
            grid: {
                left: '3%',
                right: '4%',
                bottom: '3%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                data: [],
                axisLabel: { fontSize: 12, rotate: 15 }
            },
            yAxis: {
                type: 'value',
                name: '设备数量（台）',
                nameTextStyle: { fontSize: 12 }
            },
            series: [{
                name: '设备数量',
                type: 'bar',
                data: [],
                barWidth: '60%',
                itemStyle: {
                    color: (params) => {
                        const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444'];
                        return colors[params.dataIndex % colors.length];
                    }
                },
                // 新增 label 配置
                label: {
                    show: true,                // 显示标签
                    position: 'top',            // 标签位置：top（柱子上方）、inside（柱子内部）等
                    color: '#333',               // 文字颜色
                    fontSize: 12,                // 文字大小
                    fontWeight: 'bold',          // 可选：加粗
                    formatter: '{c}'          // 自定义显示格式，{c} 代表数据值
                }
            }]
        };
        fenquChart.setOption(option);
        window.addEventListener('resize', () => fenquChart.resize());
    }



    /**
     * 从后端获取型号数量数据并更新图表（逻辑不变）
     */
    function fetchDeviceModelData(models) {
        // 核心修复：强制转为数组，兜底空数组
        const validModels = Array.isArray(models) ? models : [];

        // 改用validModels遍历（替换原models）
        const params = new URLSearchParams();
        validModels.forEach(model => params.append('models', model));

        return fetch(`/filter_device_model_count?${params.toString()}`, { signal })
            .then(response => {
                if (!response.ok) throw new Error(`请求失败：${response.status}`);
                return response.json();
            })
            .then(data => {
                if (data.code === 200) {
                    const modelNames = Object.keys(data.data);
                    const modelCounts = Object.values(data.data);

                    deviceModelChart.setOption({
                        xAxis: { data: modelNames },
                        series: [{ data: modelCounts }]
                    });

                    document.getElementById('model-total-class').textContent = modelNames.length;
                    document.getElementById('model-total-devices').textContent = data.total;
                }
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    console.debug('设备型号请求被取消:', error.message);
                    return;
                }
                console.error('获取设备型号数据失败：', error);
                deviceModelChart.setOption({ xAxis: { data: [] }, series: [{ data: [] }] });
                document.getElementById('model-total-class').textContent = 0;
                document.getElementById('model-total-devices').textContent = 0;
            });
    }

    function fetchNetworkPartitionData(fenqu) {
        // 核心修复：强制转为数组，兜底空数组
        const validFenqu = Array.isArray(fenqu) ? fenqu : [];

        // 改用validFenqu遍历（替换原fenqu）
        const params = new URLSearchParams();
        validFenqu.forEach(f => params.append('fenqu', f));

        return fetch(`/filter_fenqu_count?${params.toString()}`, { signal })
            .then(response => {
                if (!response.ok) throw new Error(`请求失败：${response.status}`);
                return response.json();
            })
            .then(data => {
                if (data.code === 200) {
                    const fenquNames = Object.keys(data.data);
                    const fenquCounts = Object.values(data.data);

                    fenquChart.setOption({
                        xAxis: { data: fenquNames },
                        series: [{ data: fenquCounts }]
                    });
                    document.getElementById('fenqu-total-class').textContent = fenquNames.length;
                    document.getElementById('fenqu-total-devices').textContent = data.total;
                }
            })
            .catch(err => {
                if (err.name === 'AbortError') {
                    console.debug('加载型号列表被取消:', err.message);
                    return;
                }
                console.error('加载型号列表失败:', err);
                fenquChart.setOption({ xAxis: { data: [] }, series: [{ data: [] }] });
                document.getElementById('fenqu-total-class').textContent = 0;
                document.getElementById('fenqu-total-devices').textContent = 0;
            });
    }


    // 绑定导出按钮事件  导出监控大屏内容为图片

    const exportBtn = document.getElementById('export-charts-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', function (e) {
            e.preventDefault();
            exportDashboardAsImage();
        });
    }

    /**
     * 异步加载设备型号列表，动态生成复选框（默认全选）
     * 并在生成后绑定全选/单选事件，同时默认勾选所有型号
     */
    async function loadDeviceModels() {
        const container = document.getElementById('model-checkbox-container');
        if (!container) return;
        try {
            const resp = await fetch('/api/device_models', { signal });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            if (data.success && Array.isArray(data.data) && data.data.length) {
                container.innerHTML = ''; // 清空“加载中”
                data.data.forEach((model, idx) => {
                    const div = document.createElement('div');
                    div.className = 'flex items-center px-4 py-2 text-sm cursor-pointer hover:bg-gray-100';
                    const cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.value = model;
                    cb.id = `model-${idx}`;
                    cb.className = 'mr-2 w-4 h-4 text-blue-500 model-checkbox';
                    // 不再设置 disabled，保持默认可用
                    const label = document.createElement('label');
                    label.htmlFor = `model-${idx}`;
                    label.className = 'cursor-pointer';
                    label.textContent = model;
                    div.appendChild(cb);
                    div.appendChild(label);
                    container.appendChild(div);
                });
                // 重新绑定事件（全选与单选）
                bindModelEvents();

                // ----- 新增：默认全选所有型号 -----
                const allCbs = container.querySelectorAll('.model-checkbox');
                allCbs.forEach(cb => cb.checked = true);
                document.getElementById('checkAllModel').checked = true;
                document.getElementById('selectedModelText').textContent = '全部型号';
                // 注意：此时外部会调用 fetchDeviceModelData([])，数据与UI状态一致
                // ---------------------------------
            } else {
                container.innerHTML = '<div class="px-4 py-2 text-sm text-gray-400">暂无设备型号数据</div>';
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                console.debug('加载型号列表被取消:', err.message);
                return;
            }
            console.error('加载型号列表失败:', err);
            container.innerHTML = '<div class="px-4 py-2 text-sm text-red-500">加载失败，请刷新重试</div>';
        }
    }

    /**
     * 异步加载业务分区列表，动态生成复选框（默认全选）
     */
    async function loadBusinessZones() {
        const container = document.getElementById('fenqu-checkbox-container');
        if (!container) return;
        try {
            const resp = await fetch('/api/business_zones', { signal });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            if (data.success && Array.isArray(data.data) && data.data.length) {
                container.innerHTML = '';
                data.data.forEach((zone, idx) => {
                    const div = document.createElement('div');
                    div.className = 'flex items-center px-4 py-2 text-sm cursor-pointer hover:bg-gray-100';
                    const cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.value = zone;
                    cb.id = `zone-${idx}`;
                    cb.className = 'mr-2 w-4 h-4 text-blue-500 fenqu-checkbox';
                    // 不再设置 disabled，保持默认可用
                    const label = document.createElement('label');
                    label.htmlFor = `zone-${idx}`;
                    label.className = 'cursor-pointer';
                    label.textContent = zone;
                    div.appendChild(cb);
                    div.appendChild(label);
                    container.appendChild(div);
                });
                bindZoneEvents();

                // ----- 新增：默认全选所有分区 -----
                const allCbs = container.querySelectorAll('.fenqu-checkbox');
                allCbs.forEach(cb => cb.checked = true);
                document.getElementById('checkAllFenqu').checked = true;
                document.getElementById('selectedFenquText').textContent = '全部分区';
                // ---------------------------------
            } else {
                container.innerHTML = '<div class="px-4 py-2 text-sm text-gray-400">暂无业务分区数据</div>';
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                console.debug('加载分区列表被取消:', err.message);
                return;
            }
            console.error('加载分区列表失败:', err);
            container.innerHTML = '<div class="px-4 py-2 text-sm text-red-500">加载失败，请刷新重试</div>';
        }
    }

    /**
     * 绑定型号复选框相关事件（全选、单选）
     */
    function bindModelEvents() {
        const checkAll = document.getElementById('checkAllModel');
        const getCheckboxes = () => document.querySelectorAll('.model-checkbox');
        const selectedTextSpan = document.getElementById('selectedModelText');

        // 全选切换
        checkAll.addEventListener('change', function () {
            const allCbs = getCheckboxes();
            if (this.checked) {
                allCbs.forEach(cb => cb.checked = true);
            } else {
                allCbs.forEach(cb => cb.checked = false);
            }
            updateModelSelection();
        });

        const updateModelSelection = () => {
            const allCbs = getCheckboxes();
            const selected = Array.from(allCbs).filter(cb => cb.checked).map(cb => cb.value);
            const total = allCbs.length;

            // 自动同步全选状态
            checkAll.checked = (selected.length === total && total > 0);

            // 更新显示文本
            if (selected.length === 0) {
                selectedTextSpan.textContent = '请选择型号';
            } else if (selected.length === total) {
                selectedTextSpan.textContent = '全部型号';
            } else if (selected.length > 2) {
                selectedTextSpan.textContent = `${selected[0]}、${selected[1]}等${selected.length}个`;
            } else {
                selectedTextSpan.textContent = selected.join('、');
            }

            // 刷新图表
            fetchDeviceModelData(selected);
        };

        // 为每个复选框绑定事件（避免重复绑定）
        getCheckboxes().forEach(cb => {
            cb.removeEventListener('change', updateModelSelection);
            cb.addEventListener('change', updateModelSelection);
        });
    }

    /**
     * 绑定业务分区相关事件
     */
    function bindZoneEvents() {
        const checkAll = document.getElementById('checkAllFenqu');
        const getCheckboxes = () => document.querySelectorAll('.fenqu-checkbox');
        const selectedTextSpan = document.getElementById('selectedFenquText');

        checkAll.addEventListener('change', function () {
            const allCbs = getCheckboxes();
            if (this.checked) {
                allCbs.forEach(cb => cb.checked = true);
            } else {
                allCbs.forEach(cb => cb.checked = false);
            }
            updateZoneSelection();
        });

        const updateZoneSelection = () => {
            const allCbs = getCheckboxes();
            const selected = Array.from(allCbs).filter(cb => cb.checked).map(cb => cb.value);
            const total = allCbs.length;

            checkAll.checked = (selected.length === total && total > 0);

            if (selected.length === 0) {
                selectedTextSpan.textContent = '请选择分区';
            } else if (selected.length === total) {
                selectedTextSpan.textContent = '全部分区';
            } else if (selected.length > 2) {
                selectedTextSpan.textContent = `${selected[0]}、${selected[1]}等${selected.length}个`;
            } else {
                selectedTextSpan.textContent = selected.join('、');
            }

            fetchNetworkPartitionData(selected);
        };

        getCheckboxes().forEach(cb => {
            cb.removeEventListener('change', updateZoneSelection);
            cb.addEventListener('change', updateZoneSelection);
        });
    }

    function initDropdownToggle(triggerId, listId, iconId) {
        const trigger = document.getElementById(triggerId);
        const list = document.getElementById(listId);
        const icon = document.getElementById(iconId);
        if (!trigger || !list) return;
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            const hidden = list.classList.contains('hidden');
            list.classList.toggle('hidden', !hidden);
            if (icon) icon.classList.toggle('rotate-180', hidden);
        });
        document.addEventListener('click', () => {
            list.classList.add('hidden');
            if (icon) icon.classList.remove('rotate-180');
        });
        list.addEventListener('click', (e) => e.stopPropagation());
    }

});
// =========导出图表--开始==========

/**
 * 通用文件下载函数（基于 fetch + Blob）
 * @param {string} url   - 导出接口地址
 * @param {HTMLElement} btn - 被点击的按钮元素
 * @param {string} filename - 下载文件名（备选）
 */
function downloadFile(url, btn, filename) {
    if (btn.disabled) return;

    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> 导出中...';

    fetch(url)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return Promise.all([response, response.blob()]);
        })
        .then(([response, blob]) => {
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            const now = new Date();
            const timestamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
            const baseName = filename.replace(/\.[^.]+$/, '');
            const ext = filename.includes('.') ? filename.substring(filename.lastIndexOf('.')) : '.xlsx';
            link.download = `${baseName}_${timestamp}${ext}`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(link.href);

            // 显示成功 Toast
            showToast(`${baseName} 导出成功！`, 'success');
        })
        .catch(error => {
            console.error('导出失败:', error);
            showToast('导出失败，请检查网络或联系管理员', 'error');
        })
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        });
}

// 导出图表为png图片
function exportDashboardAsImage() {
    const dashboardContainer = document.getElementById('body-main');
    if (!dashboardContainer) {
        showToast('未找到可导出的内容', 'error');
        return;
    }

    const exportBtn = document.getElementById('export-charts-btn');
    const originalText = exportBtn.innerHTML;
    exportBtn.disabled = true;
    exportBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> 导出中...';

    htmlToImage.toPng(dashboardContainer, {
        quality: 1.0,
        backgroundColor: '#ffffff',
        pixelRatio: window.devicePixelRatio || 1,
        width: dashboardContainer.offsetWidth,
        height: dashboardContainer.offsetHeight
    })
        .then(function (dataUrl) {
            const link = document.createElement('a');
            const now = new Date();
            const timestamp = now.toLocaleString().replace(/[/: ]/g, '');
            link.download = `信息图表_${timestamp}.png`;
            link.href = dataUrl;
            link.click();
            showToast('信息图表导出成功！', 'success');
        })
        .catch(function (error) {
            console.error('导出图片失败:', error);
            showToast('导出图片失败，请重试', 'error');
        })
        .finally(() => {
            exportBtn.disabled = false;
            exportBtn.innerHTML = originalText;
        });
}

window.addEventListener('beforeunload', function () {
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
});
// =========导出图表--结束==========
