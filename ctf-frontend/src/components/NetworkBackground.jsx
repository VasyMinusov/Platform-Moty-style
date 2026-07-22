import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import './NetworkBackground.css'

/**
 * Three.js "pentest operations" background.
 *
 * A slow, dark network topology: nodes and links floating in 3D space.
 * Colors match the platform palette (orange accent, slate blues, dark bg).
 * Rendered behind the UI with pointer-events disabled.
 */
export default function NetworkBackground() {
  const containerRef = useRef(null)
  const rafRef = useRef(null)
  const rendererRef = useRef(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    // Scene setup
    const scene = new THREE.Scene()
    scene.fog = new THREE.FogExp2(0x0f1419, 0.035)

    const camera = new THREE.PerspectiveCamera(
      60,
      container.clientWidth / container.clientHeight,
      0.1,
      100
    )
    camera.position.z = 18

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(container.clientWidth, container.clientHeight)
    renderer.setClearColor(0x0f1419, 1)
    container.appendChild(renderer.domElement)
    rendererRef.current = renderer

    // Palette
    const accent = new THREE.Color(0xe8a33d)
    const dim = new THREE.Color(0x5c6670)
    const info = new THREE.Color(0x6c93b8)
    const danger = new THREE.Color(0xd9695f)

    // Nodes
    const NODE_COUNT = 90
    const LINK_DISTANCE = 5.5
    const nodes = []

    const nodeGeo = new THREE.SphereGeometry(0.06, 8, 8)
    const nodeMat = new THREE.MeshBasicMaterial({ color: 0xffffff })
    const nodeGroup = new THREE.Group()

    for (let i = 0; i < NODE_COUNT; i++) {
      const mesh = new THREE.Mesh(nodeGeo, nodeMat.clone())
      const x = (Math.random() - 0.5) * 42
      const y = (Math.random() - 0.5) * 28
      const z = (Math.random() - 0.5) * 18
      mesh.position.set(x, y, z)

      // Color based on "role": target, router, endpoint
      const role = Math.random()
      if (role > 0.92) {
        mesh.material.color = danger
        mesh.scale.setScalar(1.6)
      } else if (role > 0.75) {
        mesh.material.color = accent
        mesh.scale.setScalar(1.3)
      } else if (role > 0.55) {
        mesh.material.color = info
      } else {
        mesh.material.color = dim
      }

      mesh.userData = {
        velocity: new THREE.Vector3(
          (Math.random() - 0.5) * 0.015,
          (Math.random() - 0.5) * 0.015,
          (Math.random() - 0.5) * 0.008
        ),
      }

      nodes.push(mesh)
      nodeGroup.add(mesh)
    }
    scene.add(nodeGroup)

    // Links as a single LineSegments object updated each frame
    const linkMat = new THREE.LineBasicMaterial({
      color: 0x2a343d,
      transparent: true,
      opacity: 0.35,
      blending: THREE.AdditiveBlending,
    })
    const linkGeo = new THREE.BufferGeometry()
    const linkPositions = new Float32Array(NODE_COUNT * NODE_COUNT * 6)
    linkGeo.setAttribute('position', new THREE.BufferAttribute(linkPositions, 3))
    const linkLines = new THREE.LineSegments(linkGeo, linkMat)
    scene.add(linkLines)

    // Subtle grid plane (radar-ish)
    const gridHelper = new THREE.GridHelper(60, 60, 0x2a343d, 0x161d24)
    gridHelper.position.y = -14
    gridHelper.rotation.x = 0.05
    scene.add(gridHelper)

    // Scanline / pulse ring
    const ringGeo = new THREE.RingGeometry(4, 4.15, 64)
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xe8a33d,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.12,
      blending: THREE.AdditiveBlending,
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.position.z = -2
    scene.add(ring)

    // Animation loop
    let time = 0
    const dummy = new THREE.Vector3()

    function animate() {
      rafRef.current = requestAnimationFrame(animate)
      time += 0.005

      // Move nodes
      nodes.forEach((node) => {
        node.position.add(node.userData.velocity)
        // Soft bounds
        if (Math.abs(node.position.x) > 22) node.userData.velocity.x *= -1
        if (Math.abs(node.position.y) > 15) node.userData.velocity.y *= -1
        if (Math.abs(node.position.z) > 10) node.userData.velocity.z *= -1
      })

      // Recompute links
      let idx = 0
      for (let i = 0; i < NODE_COUNT; i++) {
        for (let j = i + 1; j < NODE_COUNT; j++) {
          const a = nodes[i].position
          const b = nodes[j].position
          const dist = a.distanceTo(b)
          if (dist < LINK_DISTANCE) {
            linkPositions[idx++] = a.x
            linkPositions[idx++] = a.y
            linkPositions[idx++] = a.z
            linkPositions[idx++] = b.x
            linkPositions[idx++] = b.y
            linkPositions[idx++] = b.z
          }
        }
      }
      // Hide unused lines by collapsing them to the first point
      if (idx < linkPositions.length) {
        linkGeo.attributes.position.needsUpdate = true
        linkGeo.setDrawRange(0, idx / 3)
      }

      // Slow rotation of the whole topology
      nodeGroup.rotation.y = time * 0.08
      nodeGroup.rotation.x = Math.sin(time * 0.2) * 0.03
      linkLines.rotation.copy(nodeGroup.rotation)

      // Pulse ring
      const pulse = 4 + (Math.sin(time * 2) + 1) * 2.5
      ring.scale.setScalar(pulse / 4)
      ringMat.opacity = 0.12 + Math.sin(time * 2) * 0.06

      // Drift camera
      camera.position.x = Math.sin(time * 0.3) * 0.6
      camera.position.y = Math.cos(time * 0.25) * 0.4
      camera.lookAt(0, 0, 0)

      renderer.render(scene, camera)
    }

    animate()

    // Resize handler
    function onResize() {
      if (!container) return
      camera.aspect = container.clientWidth / container.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(container.clientWidth, container.clientHeight)
    }
    window.addEventListener('resize', onResize)

    return () => {
      window.removeEventListener('resize', onResize)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      renderer.dispose()
      linkGeo.dispose()
      linkMat.dispose()
      nodeGeo.dispose()
      nodes.forEach((n) => n.material.dispose())
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement)
      }
    }
  }, [])

  return <div ref={containerRef} className="network-background" aria-hidden="true" />
}


