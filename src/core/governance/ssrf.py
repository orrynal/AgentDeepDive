import socket
import urllib.parse
import ipaddress
import structlog

logger = structlog.get_logger()

def is_safe_url(url: str) -> bool:
    """Verify if a URL is safe from SSRF by checking its protocol and ensuring it resolves to a public IP."""
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning("SSRF validation failed: invalid scheme", scheme=parsed.scheme, url=url)
            return False
        
        hostname = parsed.hostname
        if not hostname:
            logger.warning("SSRF validation failed: missing hostname", url=url)
            return False
            
        # Resolve hostname to IP addresses
        try:
            ip_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            logger.warning("SSRF validation: DNS resolution failed", hostname=hostname, error=str(e))
            return False
            
        for family, _, _, _, sockaddr in ip_info:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if (
                    ip.is_loopback
                    or ip.is_private
                    or ip.is_reserved
                    or ip.is_multicast
                    or ip.is_link_local
                ):
                    logger.warning(
                        "SSRF validation blocked: restricted IP address range",
                        ip=ip_str,
                        hostname=hostname,
                        url=url,
                    )
                    return False
            except ValueError:
                logger.warning("SSRF validation: invalid IP parsed", ip=ip_str, hostname=hostname)
                return False
                
        return True
    except Exception as e:
        logger.error("SSRF validation error", url=url, error=str(e))
        return False
