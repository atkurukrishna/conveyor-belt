# ── Application Load Balancer ───────────────────────────────────────────────
resource "aws_lb" "main" {
  name               = local.prefix
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = false

  tags = { Name = local.prefix }
}

# ── Target Group ────────────────────────────────────────────────────────────
resource "aws_lb_target_group" "app" {
  name        = local.prefix
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # required for Fargate awsvpc networking

  health_check {
    path                = "/"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  # Sticky sessions pin each browser to the same task for the lifetime of a
  # pipeline run — necessary because WebSocket connections and in-memory run
  # state both live on a single task.
  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = true
  }

  tags = { Name = local.prefix }
}

# ── HTTP listener (dev) ─────────────────────────────────────────────────────
# Forwards plaintext HTTP for initial bring-up.
# TODO: replace with an HTTPS listener once an ACM certificate is available:
#
#   resource "aws_lb_listener" "https" {
#     load_balancer_arn = aws_lb.main.arn
#     port              = 443
#     protocol          = "HTTPS"
#     ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
#     certificate_arn   = var.certificate_arn        # ACM cert ARN
#     default_action {
#       type             = "forward"
#       target_group_arn = aws_lb_target_group.app.arn
#     }
#   }
#
#   # Then change this listener to redirect HTTP → HTTPS:
#   default_action {
#     type = "redirect"
#     redirect {
#       port        = "443"
#       protocol    = "HTTPS"
#       status_code = "HTTP_301"
#     }
#   }
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
