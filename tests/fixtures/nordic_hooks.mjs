// Loader hooks for make_reference.mjs: import Nordic's device code
// straight from a pc-nrfconnect-ppk checkout, with the parts that tie
// it to the desktop app replaced by stubs.
const STUBS = {
    '@nordicsemiconductor/pc-nrfconnect-shared':
        'export const logger = console; export const getAppDir = () => ".";',
    '@nordicsemiconductor/pc-nrfconnect-shared/nrfutil/device/common': '',
    child_process: 'export const fork = () => ({ on() {}, send() {}, kill() {} });',
    '../utils/persistentStore': '',
};

export function resolve(specifier, context, nextResolve) {
    if (!context.parentURL?.includes('/src/device/')) {
        return nextResolve(specifier, context);
    }
    if (specifier in STUBS) {
        const url = `data:text/javascript,${encodeURIComponent(STUBS[specifier])}`;
        return { url, shortCircuit: true };
    }
    // Their imports carry no extension; Node wants one.
    return nextResolve(specifier.startsWith('.') ? `${specifier}.ts` : specifier, context);
}
